//! 监视 PNG 变化并刷新到设备，**保持连接**；断线/被占用时自动重连。
//! 用法：cargo run --example watch -- <IP 或设备ID> <PNG> [mono|gray4|gray16]
use std::{
    fs,
    time::{Duration, SystemTime},
};

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
    let state_path = std::env::var("ZECTRIX_UI_STATE").unwrap_or_else(|_| {
        format!("{}/ui_state.txt", std::env::var("HOME").unwrap_or_default())
    });
    let pages: i32 = 4;
    let mut page: i32 = fs::read_to_string(&state_path)
        .ok()
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);

    // 外层：断线后自动重连
    loop {
        let device = open_with_retry(&target).await;
        let mut last: Option<SystemTime> = None;

        if let Ok(png) = fs::read(&path) {
            match device.show_with_format(&png, parse_format(&fmt_name)?).await {
                Ok(_) => {
                    last = fs::metadata(&path).ok().and_then(|m| m.modified().ok());
                    println!("已推送初版，开始监视文件变化…");
                }
                Err(e) => println!("首版推送失败: {e}"),
            }
        } else {
            println!("首版图片读取失败，等待文件出现…");
        }

        // 内层：监视文件 + 接收按键
        loop {
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_secs(2)) => {
                    let m = fs::metadata(&path).ok().and_then(|m| m.modified().ok());
                    if m.is_some() && m != last {
                        if let Ok(png) = fs::read(&path) {
                            match device.show_with_format(&png, parse_format(&fmt_name)?).await {
                                Ok(_) => { println!("已刷新"); last = m; }
                                Err(e) => { println!("刷新失败: {e}"); break; }   // 断开 → 重连
                            }
                        }
                    }
                }
                ev = device.next_event() => {
                    match ev {
                        Ok(Some(Event::Key { key, action })) => {
                            println!("按键 {key:?}: {action:?}");
                            if matches!(action, KeyAction::Short) {
                                match key {
                                    Key::Up => page = (page + pages - 1) % pages,
                                    Key::Down => page = (page + 1) % pages,
                                    Key::Confirm => { /* 渲染器周期重绘，无需额外动作 */ }
                                }
                                if let Err(e) = fs::write(&state_path, page.to_string()) {
                                    println!("写页面状态失败: {e}");
                                } else {
                                    println!("页面 -> {}", page);
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
