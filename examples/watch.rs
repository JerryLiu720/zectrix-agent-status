//! 监视 PNG 变化并刷新到设备，保持连接，接收按键。
//! 事件读取与图像推送**并发**：推送（2–4 秒）期间也不会漏按键。
//! 用法：cargo run --example watch -- <IP 或设备ID> <PNG> [mono|gray4|gray16]
use std::{
    fs,
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};

use tokio::sync::mpsc;
use zectrix_sdk::{Device, Event, ImageFormat, Key, KeyAction, OpenOptions};

fn parse_format(s: &str) -> Result<ImageFormat, String> {
    match s {
        "mono" => Ok(ImageFormat::Mono),
        "gray4" => Ok(ImageFormat::Gray4),
        "gray16" => Ok(ImageFormat::Gray16),
        _ => Err("图片格式只能为 mono、gray4 或 gray16".into()),
    }
}

/// FNV-1a 指纹：判断图片内容是否真的变了（比 mtime 可靠）
fn fingerprint(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

fn unix_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// 打开设备；失败时每 2 秒重试（被占用 / 断线 / 租约未释放都能自愈）
async fn open_with_retry(target: &str) -> Device {
    let mut attempt = 0u32;
    loop {
        match Device::open(OpenOptions {
            target: Some(target.to_string()),
            client_name: Some("Zectrix Watch".into()),
        })
        .await
        {
            Ok(d) => {
                if attempt > 0 {
                    println!("重连成功（第 {} 次尝试）", attempt + 1);
                }
                return d;
            }
            Err(e) => {
                attempt += 1;
                println!("连接失败（第 {attempt} 次）: {e}；2 秒后重试…");
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if !(3..=4).contains(&args.len()) {
        return Err("用法：watch <IP 或设备 ID> <PNG 文件> [mono|gray4|gray16]".into());
    }
    let target = args[1].clone();
    let path = args[2].clone();
    let fmt_name = args.get(3).map(String::as_str).unwrap_or("gray16").to_string();
    parse_format(&fmt_name)?;

    // 所有状态文件与 PNG 同目录（渲染器按同样约定读写）
    let dir = std::path::Path::new(&path)
        .parent()
        .map(|d| d.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."));
    let state_path = std::env::var("ZECTRIX_UI_STATE").unwrap_or_else(|_| {
        dir.join("ui_state.txt").to_string_lossy().into_owned()
    });
    let hb_path = dir.join("conn.txt"); // 心跳：渲染器据此判断连接状态
    let act_path = dir.join("active.txt"); // 渲染器写的"是否在对话中"
    let bat_path = dir.join("battery.txt"); // 电量：百分比,充电中(1/0)
    let pages_path = dir.join("pages.txt"); // 渲染器写的页数

    let pages: i32 = fs::read_to_string(&pages_path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .filter(|n: &i32| *n > 0 && *n <= 12)
        .unwrap_or(4);
    let mut page: i32 = fs::read_to_string(&state_path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);

    // 外层：断线后自动重连
    loop {
        let device = Arc::new(open_with_retry(&target).await);

        // 独立协程持续消费事件：推送图像时按键也不会丢
        let (tx, mut rx) = mpsc::channel::<Event>(128);
        {
            let d = device.clone();
            tokio::spawn(async move {
                loop {
                    match d.next_event().await {
                        Ok(Some(ev)) => {
                            if tx.send(ev).await.is_err() {
                                break;
                            }
                        }
                        _ => break,
                    }
                }
            });
        }

        let _ = fs::write(&hb_path, format!("{}", unix_now()));

        // 连接后读一次电量
        if let Ok(st) = device.status().await {
            let pct = st.battery_percent.unwrap_or(0);
            let ch = if st.charging.unwrap_or(false) { 1 } else { 0 };
            let _ = fs::write(&bat_path, format!("{pct},{ch}"));
            println!("电量 {pct}%{}", if ch == 1 { "（充电中）" } else { "" });
        }

        let mut last_fp: u64 = 0;
        let mut last_push = Instant::now() - Duration::from_secs(600);
        let mut pending = false;
        let mut last_key: Option<(Key, Instant)> = None;
        let mut last_hb = Instant::now() - Duration::from_secs(11);
        let mut last_bat = Instant::now();

        if let Ok(png) = fs::read(&path) {
            match device.show_with_format(&png, parse_format(&fmt_name)?).await {
                Ok(_) => {
                    last_fp = fingerprint(&png);
                    last_push = Instant::now();
                    println!("已推送初版，开始监视文件变化…");
                }
                Err(e) => println!("首版推送失败: {e}"),
            }
        } else {
            println!("首版图片读取失败，等待文件出现…");
        }

        // 内层：按键（来自队列）+ 周期性检查
        loop {
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_millis(200)) => {
                    if last_hb.elapsed() >= Duration::from_secs(10) {
                        let _ = fs::write(&hb_path, format!("{}", unix_now()));
                        last_hb = Instant::now();
                    }
                    if last_bat.elapsed() >= Duration::from_secs(300) {
                        if let Ok(st) = device.status().await {
                            let pct = st.battery_percent.unwrap_or(0);
                            let ch = if st.charging.unwrap_or(false) { 1 } else { 0 };
                            let _ = fs::write(&bat_path, format!("{pct},{ch}"));
                        }
                        last_bat = Instant::now();
                    }

                    if pending {
                        // 连按合并：最后一次按键后静默 300ms 再推
                        if let Some((_, lt)) = last_key {
                            if lt.elapsed() < Duration::from_millis(300) {
                                continue;
                            }
                        }
                    } else {
                        let active = fs::read_to_string(&act_path)
                            .map(|s| s.trim() == "1")
                            .unwrap_or(false);
                        let interval = if active { 60 } else { 300 };
                        if last_push.elapsed() < Duration::from_secs(interval) {
                            continue;
                        }
                    }

                    if let Ok(png) = fs::read(&path) {
                        let fp = fingerprint(&png);
                        if fp != last_fp {
                            match device.show_with_format(&png, parse_format(&fmt_name)?).await {
                                Ok(_) => {
                                    println!("已刷新{}", if pending { "（按键）" } else { "" });
                                    last_fp = fp;
                                    last_push = Instant::now();
                                    pending = false;
                                }
                                Err(e) => { println!("刷新失败: {e}"); break; }
                            }
                        } else if pending {
                            pending = false;
                        }
                    }
                }
                maybe_ev = rx.recv() => {
                    match maybe_ev {
                        Some(Event::Key { key, action }) => {
                            // 确认键（短按/长按）= 立即重推当前页
                            if matches!(key, Key::Confirm) {
                                if let Ok(png) = fs::read(&path) {
                                    match device.show_with_format(&png, parse_format(&fmt_name)?).await {
                                        Ok(_) => {
                                            println!("已刷新（确认键）");
                                            last_fp = fingerprint(&png);
                                            last_push = Instant::now();
                                            pending = false;
                                        }
                                        Err(e) => println!("刷新失败: {e}"),
                                    }
                                }
                                continue;
                            }
                            // 只响应短按；长按的 Long 忽略（映射成跳页会像乱跳）
                            match (action, key) {
                                (KeyAction::Short, Key::Up) => page = (page + pages - 1) % pages,
                                (KeyAction::Short, Key::Down) => page = (page + 1) % pages,
                                _ => continue,
                            }
                            // 去抖：同键 60ms 内重复视为硬件抖动
                            if let Some((lk, lt)) = last_key {
                                if lk == key && lt.elapsed() < Duration::from_millis(60) {
                                    println!("忽略抖动 {key:?}");
                                    continue;
                                }
                            }
                            last_key = Some((key, Instant::now()));
                            let _ = fs::write(&state_path, page.to_string());
                            println!("按键 {key:?} → 第 {} 页", page + 1);
                            pending = true;
                        }
                        Some(Event::Disconnected { .. }) => { println!("设备已断开，准备重连…"); break; }
                        Some(_) => {}
                        None => { println!("事件流结束，准备重连…"); break; }
                    }
                }
            }
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}
