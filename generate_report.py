"""
generate_report.py
매일 새벽 4시에 실행되어 report.json을 생성합니다.
"""

import json
import os
import datetime
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

# ── 설정 ──────────────────────────────────────────────
KST = ZoneInfo("Asia/Tokyo")   # 일본/한국 표준시 (UTC+9)
now       = datetime.datetime.now(KST)
today     = now.date()
yesterday = today - datetime.timedelta(days=1)
tomorrow  = today + datetime.timedelta(days=1)

WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")

ICAL_URLS = [
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCIVP58eGmQm8cjZa9KDDBF9vv8SoApAB7gMPuYjpGnH98fB8YWpMvUQeizQXhsRZYU",
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCJrKUsO_AW5w6v0v7oNHYHd5WsV_bMsDk3ACrtnjpxRLabjLsx6CvWdC053Tr3Ss-g",
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCL-WdRUZNC9M2efypMusaAxOrdpLbYaR1k0kC7y_jLkePUEckPoFCXcbO9OSoe0tAQ",
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCIoHyRjBOE4G3iJ_M_buNvEZ002XGdl5_L-zSwB2nVANnvgPEFdRe6Br16WHVu4Ipc",
    "https://p33-caldav.icloud.com/published/2/MTAwMzk4NDcwNTEwMDM5OIKMqbxDECSm4-w6pcPcOCKfMnmOVmqGDC8rvy7RkR9ttHeHkOs1HcsaMSF6tViJlgCHQCsV2zJ1gSjmaCPg6Ow",
    "https://calendar.google.com/calendar/ical/ko.south_korea%23holiday%40group.v.calendar.google.com/public/basic.ics",
    "https://calendars.icloud.com/holidays/jp_ja.ics",
]

# ── 날씨 ──────────────────────────────────────────────
def get_weather():
    """OpenWeatherMap API로 오늘 아침/낮/저녁 날씨 가져오기 (나가노 기준)"""
    if not WEATHER_API_KEY:
        return {"morning": "날씨 API 키 없음", "afternoon": "", "evening": ""}
    try:
        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?q=Nagano,JP&appid={WEATHER_API_KEY}&units=metric&lang=kr"
        )
        r = requests.get(url, timeout=10)
        data = r.json()

        targets = {"morning": 6, "afternoon": 12, "evening": 18}
        result = {}

        for key, target_hour in targets.items():
            best = None
            best_diff = 999
            for item in data.get("list", []):
                dt = datetime.datetime.fromtimestamp(item["dt"], tz=KST)
                if dt.date() != today:
                    continue
                diff = abs(dt.hour - target_hour)
                if diff < best_diff:
                    best_diff = diff
                    best = item

            if best:
                desc = best["weather"][0]["description"]
                temp = round(best["main"]["temp"])
                main = best["weather"][0]["main"].lower()
                if "rain" in main or "drizzle" in main or "thunderstorm" in main:
                    label = "비"
                elif "cloud" in main:
                    label = "흐림"
                elif "snow" in main:
                    label = "눈"
                else:
                    label = "맑음"
                result[key] = f"{label} ({desc}, {temp}°C)"
            else:
                result[key] = "정보 없음"

        return result
    except Exception as e:
        return {"morning": f"날씨 오류: {e}", "afternoon": "", "evening": ""}


# ── 성무일도 ───────────────────────────────────────────
def get_liturgy():
    """catholic.or.kr 성무일도 아침기도 본문 추출."""
    try:
        date_str = today.strftime("%Y-%m-%d")
        headers = {"User-Agent": "Mozilla/5.0"}
        url = (
            f"https://maria.catholic.or.kr/mi_pr/sungmu/sungmu.asp"
            f"?menu=sungmu&sunseo=1&gomonth={date_str}&stype=mo"
        )
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        full_text = soup.get_text(separator="\n")
        lines = [l.strip() for l in full_text.splitlines()]

        start_idx = None
        for i, line in enumerate(lines):
            if "날 구하소서" in line:
                start_idx = i
                break

        if start_idx is None:
            tables = soup.find_all("table")
            fallback = []
            for table in tables:
                t = table.get_text(separator="\n")
                if "하느님" in t or "찬미" in t or "시편" in t:
                    for line in t.splitlines():
                        line = line.strip()
                        if line:
                            fallback.append(line)
            return "\n".join(fallback) if fallback else "아침기도 본문을 찾지 못했습니다."

        found_pagen = False
        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if "파견" in lines[i]:
                found_pagen = True
            if found_pagen and any(kw in lines[i] for kw in [
                "이용약관", "ⓒ GoodNews", "서울대교구", "goodnews@",
                "매일미사", "가톨릭기도서", "7성사",
                "(구)성경쓰기", "미사/기도서", "말씀나누기", "성경책갈피", "내 교구"
            ]):
                end_idx = i
                break
            if not found_pagen and any(kw in lines[i] for kw in [
                "이용약관", "ⓒ GoodNews", "서울대교구", "goodnews@",
                "(구)성경쓰기", "미사/기도서"
            ]):
                end_idx = i
                break

        result = []
        for line in lines[start_idx:end_idx]:
            if line and not any(bad in line for bad in [
                "goodnews", "catholic.or.kr", "이용약관",
                "개인정보", "ⓒ", "글자크기", "quick"
            ]):
                result.append(line)

        return "\n".join(result) if result else "아침기도 본문을 찾지 못했습니다."
    except Exception as e:
        return f"성무일도 오류: {e}"


# ── 오늘의 복음 ────────────────────────────────────────
def get_gospel(target_date=None):
    """catholic.or.kr 미사 페이지에서 독서/복음 스크래핑."""
    import re
    if target_date is None:
        target_date = today
    result = {"reading1": "", "reading2": "", "gospel": ""}
    try:
        date_str = target_date.strftime("%Y-%m-%d")
        url = (
            f"https://maria.catholic.or.kr/mi_pr/missa/missa.asp"
            f"?menu=missa&gomonth={date_str}&missatype=DA"
        )
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        raw = soup.get_text(separator="\n")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]

        date_pattern = re.compile(r"\d{4}년 \d+월 \d+일")
        target_year  = target_date.strftime("%Y년")
        target_month = str(target_date.month) + "월"
        target_day   = str(target_date.day) + "일"
        body_start = 0
        for i, line in enumerate(lines):
            if (date_pattern.search(line) and target_year in line
                    and target_month in line and target_day in line):
                body_start = i
                break
        else:
            for i, line in enumerate(lines):
                if date_pattern.search(line):
                    body_start = i
                    break

        lines = lines[body_start:]

        sections = {"reading1": [], "reading2": [], "gospel": []}
        current = None
        reading1_done = False

        for line in lines:
            if "제1독서" in line and current is None and not reading1_done:
                current = "reading1"
                sections["reading1"].append(line)
                continue
            if "제2독서" in line and current is None:
                current = "reading2"
                sections["reading2"].append(line)
                continue
            if ("✠" in line or "거룩한 복음입니다" in line) and current != "gospel":
                current = "gospel"
                sections["gospel"].append(line)
                continue

            if current == "reading1":
                if "주님의 말씀입니다" in line or "하느님 감사합니다" in line:
                    sections["reading1"].append(line)
                    current = None
                    reading1_done = True
                elif any(kw in line for kw in ["화답송", "알렐루야", "복음 환호송", "제2독서"]):
                    current = None
                    reading1_done = True
                else:
                    sections["reading1"].append(line)
            elif current == "reading2":
                if "주님의 말씀입니다" in line or "하느님 감사합니다" in line:
                    sections["reading2"].append(line)
                    current = None
                elif any(kw in line for kw in ["화답송", "알렐루야", "복음 환호송"]):
                    current = None
                else:
                    sections["reading2"].append(line)
            elif current == "gospel":
                sections["gospel"].append(line)
                if "그리스도님, 찬미합니다" in line:
                    current = None
                    break

        result["reading1"] = "\n".join(sections["reading1"])
        result["reading2"] = "\n".join(sections["reading2"])
        result["gospel"]   = "\n".join(sections["gospel"])

    except Exception as e:
        result["reading1"] = f"복음 오류: {e}"
    return result


# ── iCloud 캘린더 ──────────────────────────────────────
def get_calendar_events(date: datetime.date) -> list:
    """여러 iCloud 공개 캘린더 URL(.ics)에서 해당 날짜 일정 가져오기."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}

        # 모든 캘린더 URL에서 줄 수집
        all_lines = []
        for ical_url in ICAL_URLS:
            try:
                r = requests.get(ical_url, headers=headers, timeout=15)
                r.encoding = "utf-8"
                all_lines.extend(r.text.splitlines())
            except Exception as e:
                print(f"캘린더 URL 오류: {e}")

        # 멀티라인 언폴딩 (RFC 5545)
        unfolded = []
        for line in all_lines:
            if line.startswith((" ", "\t")) and unfolded:
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line)

        # 이벤트 파싱
        events = []
        in_event = False
        current = {}
        for line in unfolded:
            s = line.strip()
            if s == "BEGIN:VEVENT":
                in_event = True
                current = {}
            elif s == "END:VEVENT":
                in_event = False
                if current:
                    events.append(current)
            elif in_event:
                if s.startswith("SUMMARY"):
                    current["summary"] = s.split(":", 1)[-1].strip()
                elif s.startswith("DTSTART"):
                    current["dtstart"] = s.split(":", 1)[-1].strip()
                elif s.startswith("DTEND"):
                    current["dtend"] = s.split(":", 1)[-1].strip()

        # 해당 날짜 필터링
        date_str_basic = date.strftime("%Y%m%d")
        result = []

        for e in events:
            dtstart = e.get("dtstart", "")
            summary = e.get("summary", "(제목 없음)")

            # 종일 일정: 20260501
            if len(dtstart) == 8 and dtstart == date_str_basic:
                result.append(f"종일 {summary}")
            # 날짜+시간: 20260501T120000Z 또는 20260501T210000
            elif len(dtstart) > 8 and dtstart.startswith(date_str_basic):
                try:
                    if dtstart.endswith("Z"):
                        t = datetime.datetime.strptime(dtstart, "%Y%m%dT%H%M%SZ")
                        t = t.replace(tzinfo=datetime.timezone.utc).astimezone(KST)
                    else:
                        t = datetime.datetime.strptime(dtstart[:15], "%Y%m%dT%H%M%S")
                    result.append(f"{t.strftime('%H:%M')} {summary}")
                except Exception:
                    result.append(f"- {summary}")

        result.sort()
        print(f"{date} 일정 {len(result)}개")
        return result if result else ["일정 없음"]

    except Exception as e:
        return [f"캘린더 오류: {e}"]


# ── 신문 RSS ───────────────────────────────────────────
def get_news(paper_key: str) -> list:
    """각 신문사 RSS에서 기사 제목 3개 추출"""
    rss_urls = {
        "hankyoreh": "https://www.hani.co.kr/rss/",
        "chosun":    "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
        "jtbc":      "https://fs.jtbc.co.kr/RSS/newsflash.xml",
        "donga":     "https://rss.donga.com/total.xml",
    }
    url = rss_urls.get(paper_key)
    if not url:
        return ["RSS 주소 없음"]
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.content, "xml")
        items = soup.find_all("item")[:3]
        return [item.find("title").get_text(strip=True) for item in items if item.find("title")]
    except Exception as e:
        return [f"오류: {e}"]


# ── 메인 ───────────────────────────────────────────────
def main():
    print("리포트 생성 시작...")

    report = {
        "date":            today.strftime("%Y-%m-%d"),
        "generated_at":    now.strftime("%Y-%m-%d %H:%M"),
        "weather":         get_weather(),
        "liturgy":         get_liturgy(),
        "gospel":          get_gospel(today),
        "gospel_tomorrow": get_gospel(tomorrow),
        "calendar": {
            "yesterday": get_calendar_events(yesterday),
            "today":     get_calendar_events(today),
            "tomorrow":  get_calendar_events(tomorrow),
        },
        "news": {
            "hankyoreh": get_news("hankyoreh"),
            "chosun":    get_news("chosun"),
            "jtbc":      get_news("jtbc"),
            "donga":     get_news("donga"),
        }
    }

    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("report.json 생성 완료!")


if __name__ == "__main__":
    main()
