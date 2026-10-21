//! 监视 PNG 变化并刷新到设备，**保持连接**；断线/被占用时自动重连。
//! 用法：cargo run --example watch -- <IP 或设备ID> <PNG> [mono|gray4|gray16]
use std::{
    fs,
    time::{Duration, Instant},
};

/// FNV-1a 指纹：判断图片内容是否真的变了（比 mtime 可靠）
fn fingerprint(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for &b in bytes {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

use zectrix_sdk::{Device, Event, ImageFormat, Key, KeyAction, OpenOptions};

fn parse_format(s: &str) -> Result<ImageFormat, String> {
    match s {
        "mono" => Ok(ImageFormat::Mono),
        "gray4" => Ok(ImageFormat::Gray4),
        "gray16" => Ok(ImageFormat::Gray16),
        _ => Err("图片格式只能为 mono、gray4 或 gray16".into()),
    }
}

/// 打开设备；失败时每 2 秒重试（设备被占用/租约未释放/Busy 都能自愈）
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

    // 页面状态：纯文本文件（供 Python 渲染器读取，零依赖）
    // 页码文件放在 PNG 同目录（与渲染器约定一致，避免 HOME 拼接错误）
    let state_path = std::env::var("ZECTRIX_UI_STATE").unwrap_or_else(|_| {
        std::path::Path::new(&path)
            .parent()
            .map(|d| d.join("ui_state.txt").to_string_lossy().into_owned())
            .unwrap_or_else(|| "ui_state.txt".to_string())
    });
    let dir = std::path::Path::new(&path).parent().map(|d| d.to_path_buf())
        .unwrap_or_else(|| std::path::PathBuf::from("."));
    let hb_path = dir.join("conn.txt");      // 心跳：渲染器据此判断"连接状态"
    let act_path = dir.join("active.txt");   // 渲染器写的"是否在对话中"
    let bat_path = dir.join("battery.txt"); // 电量：百分比,充电中(1/0)
    let pages: i32 = 4;
    let mut page: i32 = fs::read_to_string(&state_path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);

    // 外层：断线后自动重连
    loop {
        let device = open_with_retry(&target).await;
        let _ = fs::write(&hb_path, format!("{}", std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)));
        if let Ok(st) = device.status().await {
            let pct = st.battery_percent.unwrap_or(0);
            let ch = if st.charging.unwrap_or(false) { 1 } else { 0 };
            let _ = fs::write(&bat_path, format!("{pct},{ch}"));
            println!("电量 {pct}%{}", if ch == 1 { "（充电中）" } else { "" });
        }
        let mut last_hb = Instant::now();
        let mut last_bat = Instant::now();
        let mut last_fp: u64 = 0;
        let mut last_push = Instant::now() - Duration::from_secs(600);

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

        // 内层：接收按键 + 兜底刷新（数据类变化每 5 分钟最多一次）
        loop {
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_secs(2)) => {
                    // 每 10 秒心跳一次（不碰设备，只写文件）
                    if last_hb.elapsed() >= Duration::from_secs(10) {
                        let _ = fs::write(&hb_path, format!("{}", std::time::SystemTime::now()
                            .duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)));
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
                    // 对话进行中 60 秒刷一次（时间保持新鲜），空闲 5 分钟
                    let active = fs::read_to_string(&act_path).map(|s| s.trim() == "1").unwrap_or(false);
                    let interval = if active { 60 } else { 300 };
                    if last_push.elapsed() < Duration::from_secs(interval) {
                        continue;
                    }
                    if let Ok(png) = fs::read(&path) {
                        let fp = fingerprint(&png);
                        if fp != last_fp {
                            match device.show_with_format(&png, parse_format(&fmt_name)?).await {
                                Ok(_) => { println!("已自动刷新"); last_fp = fp; last_push = Instant::now(); }
                                Err(e) => { println!("刷新失败: {e}"); break; }
                            }
                        }
                    }
                }
                ev = device.next_event() => {
                    match ev {
                        Ok(Some(Event::Key { key, action })) => {
                            println!("按键 {key:?}: {action:?}");
                            // 确认键 = 立即重推当前页
                            if matches!(action, KeyAction::Short) && matches!(key, Key::Confirm) {
                                if let Ok(png) = fs::read(&path) {
                                    match device.show_with_format(&png, parse_format(&fmt_name)?).await {
                                        Ok(_) => {
                                            println!("已刷新（确认键）");
                                            last_fp = fingerprint(&png);
                                            last_push = Instant::now();
                                        }
                                        Err(e) => println!("刷新失败: {e}"),
                                    }
                                }
                                continue;
                            }
                            if matches!(action, KeyAction::Short) {
                                match key {
                                    Key::Up => page = (page + pages - 1) % pages,
                                    Key::Down => page = (page + 1) % pages,
                                    Key::Confirm => unreachable!(),
                                }
                                let _ = fs::write(&state_path, page.to_string());
                                println!("页面 -> {}", page);

                                // 原地等渲染器产出新图，然后立刻推送（最多 6 秒）
                                let mut done = false;
                                for _ in 0..30 {
                                    tokio::time::sleep(Duration::from_millis(200)).await;
                                    if let Ok(png) = fs::read(&path) {
                                        let fp = fingerprint(&png);
                                        if fp != last_fp {
                                            match device.show_with_format(&png, parse_format(&fmt_name)?).await {
                                                Ok(_) => {
                                                    println!("已刷新");
                                                    last_fp = fp;
                                                    last_push = Instant::now();
                                                    done = true;
                                                }
                                                Err(e) => println!("刷新失败: {e}"),
                                            }
                                            break;
                                        }
                                    }
                                }
                                if !done {
                                    println!("第 {} 页未产生新图（渲染器可能未运行）", page);
                                }
                            }
                        }
                        Ok(Some(Event::Disconnected { .. })) => { println!("设备已断开，准备重连…"); break; }
                        Ok(Some(_)) => {}
                        Ok(None) => break,
                        Err(e) => { println!("事件错误: {e}，准备重连…"); break; }
                    }
                }
            }
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}
