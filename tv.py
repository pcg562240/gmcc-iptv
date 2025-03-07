import json
import re
import os
import requests
import sys
import gzip
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ===================== 自定义配置区域 =====================
# 在这里修改输出文件名（保持默认即可使用原始文件名）
TV_M3U_FILENAME = "tv.m3u"        # 组播地址列表文件
TV2_M3U_FILENAME = "tv2.m3u"      # 转单播地址列表文件
XML_FILENAME = "t.xml"            # XML节目单文件
REPLACEMENT_IP = "http://10.10.10.253:3333/rtp/"  # UDPXY地址
# ========================================================

# 自动生成的压缩文件名（基于XML文件名）
XML_GZ_FILENAME = XML_FILENAME + ".gz"

# 打印当前使用的UDPXY地址
print(f"你的组播转单播UDPXY地址是 {REPLACEMENT_IP}")

# JSON 文件下载 URL
JSON_URL = "http://183.235.16.92:8082/epg/api/custom/getAllChannel.json"

def download_json_data(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        print(f"成功获取 JSON 数据从 {url}")
        return data
    except requests.RequestException as e:
        print(f"下载 JSON 数据失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"解析 JSON 数据失败: {e}")
        return None

def categorize_channel(title):
    if "CCTV" in title:
        return "央视"
    elif "广东" in title or "大湾区" in title or "嘉佳" in title or "南方" in title or "岭南" in title:
        return "广东"
    elif "卫视" in title:
        return "卫视"
    else:
        return "其他"

def extract_number(title):
    match = re.search(r'\d+', title)
    return int(match.group()) if match else 0

def generate_download_urls(channels):
    current_date = datetime.now().strftime("%Y%m%d")
    next_date = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    base_url = "http://183.235.16.92:8082/epg/api/channel/"
    urls = []

    for channel in channels:
        code = channel["code"]
        urls.append(f"{base_url}{code}.json?begintime={current_date}")
        urls.append(f"{base_url}{code}.json?begintime={next_date}")
    
    return urls

def convert_time_to_xmltv_format(time_str):
    try:
        return f"{time_str} +0800"
    except ValueError as e:
        print(f"时间格式转换失败: {time_str}, 错误: {e}")
        return None

def download_and_save_all_schedules(urls, grouped_channels, output_file=XML_FILENAME):
    all_schedules = {}
    total_urls = len(urls)
    success_count = 0
    failed_count = 0

    print("正在下载节目单...")

    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            code = url.split('/channel/')[1].split('.json')[0]

            if code not in all_schedules:
                all_schedules[code] = {
                    "channel": data.get("channel", {}),
                    "schedules": []
                }

            all_schedules[code]["schedules"].extend(data.get("schedules", []))
            success_count += 1
            print(f"\r成功获取{success_count}/{total_urls}个节目单...", end="")
        except Exception as e:
            print(f"\n处理 {url} 失败: {e}")
            failed_count += 1

    print("\n")

    root = ET.Element("tv")
    root.set("generator-info-name", "Custom EPG Generator")

    group_order = ["央视", "广东", "卫视", "其他"]
    for group in group_order:
        if group in grouped_channels:
            for channel_entry in grouped_channels[group]:
                code = channel_entry["code"]
                if code not in all_schedules:
                    continue

                channel_data = all_schedules[code]
                channel_info = channel_data.get("channel", {})

                channel = ET.SubElement(root, "channel")
                channel.set("id", code)
                
                display_name = ET.SubElement(channel, "display-name")
                display_name.text = channel_info.get("title", "Unknown Channel")
                
                if icon_url := channel_info.get("icon", ""):
                    ET.SubElement(channel, "icon").set("src", icon_url)

                for schedule in channel_data.get("schedules", []):
                    programme = ET.SubElement(root, "programme")
                    programme.set("channel", code)
                    
                    if (start := convert_time_to_xmltv_format(schedule.get("starttime", ""))) and \
                       (end := convert_time_to_xmltv_format(schedule.get("endtime", ""))):
                        programme.set("start", start)
                        programme.set("stop", end)

                    title = ET.SubElement(programme, "title")
                    title.set("lang", "zh")
                    title.text = schedule.get("title", "Unknown Programme")

    xml_str = minidom.parseString(ET.tostring(root, encoding='utf-8')).toprettyxml(indent="  ")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(xml_str)

    print(f"已保存节目单XML文件到: {os.path.abspath(output_file)}")

    with open(output_file, 'rb') as f_in:
        with gzip.open(XML_GZ_FILENAME, 'wb') as f_out:
            f_out.writelines(f_in)

    print(f"已生成压缩文件: {os.path.abspath(XML_GZ_FILENAME)}")
    print(f"下载完成！成功: {success_count}, 失败: {failed_count}")

if __name__ == "__main__":
    data = download_json_data(JSON_URL)
    if data is None:
        print("程序退出")
        sys.exit(1)

    channels = data["channels"]
    grouped_channels = {"央视": [], "广东": [], "卫视": [], "其他": []}

    for channel in channels:
        category = categorize_channel(channel["title"])
        grouped_channels[category].append({
            "title": channel["title"],
            "code": channel["code"],
            "icon": channel["icon"],
            "hwurl": channel["params"]["hwurl"],
            "number": extract_number(channel["title"])
        })

    for category in grouped_channels:
        grouped_channels[category].sort(key=lambda x: (x["number"], x["title"]))

    def generate_m3u_content(grouped_channels, replace_url):
        content = ["#EXTM3U"]
        for group in ["央视", "广东", "卫视", "其他"]:
            for ch in grouped_channels.get(group, []):
                url = ch["hwurl"].replace("rtp://", REPLACEMENT_IP) if replace_url else ch["hwurl"]
                content.append(f'#EXTINF:-1 tvg-id="{ch["code"]}" tvg-name="{ch["title"]}" tvg-logo="{ch["icon"]}" group-title="{group}",{ch["title"]}\n{url}')
        return '\n'.join(content)

    # 生成M3U文件
    for filename, content in [
        (TV_M3U_FILENAME, generate_m3u_content(grouped_channels, False)),
        (TV2_M3U_FILENAME, generate_m3u_content(grouped_channels, True))
    ]:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)

    total_channels = sum(len(v) for v in grouped_channels.values())
    print(f"\n成功生成 {total_channels} 个频道")
    print(f"组播地址列表: {os.path.abspath(TV_M3U_FILENAME)}")
    print(f"单播地址列表: {os.path.abspath(TV2_M3U_FILENAME)}")

    print("\n开始下载节目单...")
    download_and_save_all_schedules(generate_download_urls(channels), grouped_channels)