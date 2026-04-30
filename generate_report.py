"""
generate_report.py
매일 새벽 1시에 실행되어 report.json을 생성합니다.
"""

import json
import os
import datetime
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

# ── 설정 ──────────────────────────────────────────────
KST = ZoneInfo("Asia/Tokyo")   # 일본/한국 표준시 (UTC+9)
now    = datetime.datetime.now(KST)
today  = now.date()
yesterday = today - datetime.timedelta(days=1)
tomorrow  = today + datetime.timedelta(days=1)

WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")   # OpenWeatherMap API 키
GOOGLE_CALENDAR_CREDS = os.environ.get("GOOGLE_CALENDAR_CREDS", "")  # JSON 문자열
CALENDAR_ID = os.environ.get("CALENDAR_ID", "primary")

# ── 날씨 ──────────────────────────────────────────────
def get_weather():
    """OpenWeatherMap API로 날씨 가져오기 (나가노 기준)"""
    if not WEATHER_API_KEY:
        return "날씨 API 키 없음"
    try:
        url = (
            "https://api.openweathermap.org/data/2.5/weather"
            f"?q=Nagano,JP&appid={WEATHER_API_KEY}&units=metric&lang=kr"
        )
        r = requests.get(url, timeout=10)
        d = r.json()
        desc = d["weather"][0]["description"]
        temp = round(d["main"]["temp"])

        # 맑음/흐림/비 분류
        main = d["weather"][0]["main"].lower()
        if "rain" in main or "drizzle" in main or "thunderstorm" in main:
            label = "비"
        elif "cloud" in main:
            label = "흐림"
        else:
            label = "맑음"

        return f"{label} ({desc}, {temp}°C)"
    except Exception as e:
        return f"날씨 정보 오류: {e}"


# ── 성무일도 ───────────────────────────────────────────
def get_liturgy():
    """catholic.or.kr 성무일도 본문 스크래핑"""
    try:
        url = "https://maria.catholic.or.kr/mi_pr/sungmu/sungmu.asp"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")

        # 사이드메뉴 제거 — 사이트 구조에 맞게 선택자 조정 필요
        for tag in soup.select(".leftmenu, .sidemenu, #leftmenu, #sidemenu, .gnb"):
            tag.decompose()

        # 본문 영역 추출 (td.body_text 또는 div.content 등 사이트 구조에 따라 조정)
        body = soup.select_one("td.body_text") or soup.select_one(".content_area") or soup.find("body")
        text = body.get_text(separator="\n").strip() if body else "본문 없음"

        # 연속 빈 줄 정리
        lines = [l for l in text.splitlines() if l.strip()]
        return "\n".join(lines)
    except Exception as e:
        return f"성무일도 오류: {e}"


# ── 오늘의 복음 ────────────────────────────────────────
def get_gospel():
    """catholic.or.kr 미사 페이지에서 독서/복음 스크래핑"""
    result = {"reading1": "", "reading2": "", "gospel": ""}
    try:
        url = "https://maria.catholic.or.kr/mi_pr/missa/missa.asp"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")

        # 사이드메뉴 제거
        for tag in soup.select(".leftmenu, .sidemenu, #leftmenu, #sidemenu, .gnb"):
            tag.decompose()

        text = soup.get_text(separator="\n")
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        # 제1독서, 제2독서, 복음 구간 파싱
        sections = {"reading1": [], "reading2": [], "gospel": []}
        current = None
        for line in lines:
            if "제1독서" in line:
                current = "reading1"
            elif "제2독서" in line:
                current = "reading2"
            elif "복음" in line and "말씀" not in line and current != "gospel":
                current = "gospel"
            elif current:
                # 다음 섹션 시작 감지 시 중단
                if any(kw in line for kw in ["강론", "화답송", "알렐루야", "저작권"]):
                    if current == "reading1" and sections["reading1"]:
                        current = None
                    elif current == "gospel" and sections["gospel"]:
                        current = None
                else:
                    sections[current].append(line)

        result["reading1"] = "\n".join(sections["reading1"])
        result["reading2"] = "\n".join(sections["reading2"])
        result["gospel"]   = "\n".join(sections["gospel"])
    except Exception as e:
        result["reading1"] = f"복음 오류: {e}"
    return result


# ── 구글 캘린더 ────────────────────────────────────────
def get_calendar_events(date: datetime.date) -> list:
    """Google Calendar API로 특정 날짜의 일정 가져오기"""
    if not GOOGLE_CALENDAR_CREDS:
        return ["(캘린더 설정 필요)"]
    try:
        import tempfile
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        # Secrets에서 가져온 JSON 문자열을 임시 파일로 저장
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(GOOGLE_CALENDAR_CREDS)
            cred_path = f.name

        creds = service_account.Credentials.from_service_account_file(
            cred_path,
            scopes=["https://www.googleapis.com/auth/calendar.readonly"]
        )
        os.unlink(cred_path)

        service = build("googleapiclient", "v3", credentials=creds)

        # 날짜 범위 (KST 기준)
        start = datetime.datetime.combine(date, datetime.time.min).replace(tzinfo=KST).isoformat()
        end   = datetime.datetime.combine(date, datetime.time.max).replace(tzinfo=KST).isoformat()

        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])
        result = []
        for e in events:
            start_val = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start_val:
                t = datetime.datetime.fromisoformat(start_val).astimezone(KST)
                time_str = t.strftime("%H:%M")
            else:
                time_str = "종일"
            result.append(f"{time_str} {e.get('summary', '(제목 없음)')}")

        return result if result else ["일정 없음"]
    except Exception as e:
        return [f"캘린더 오류: {e}"]


# ── 신문 RSS ───────────────────────────────────────────
def get_news(paper_key: str) -> list:
    """각 신문사 RSS에서 기사 제목 3개 추출"""
    rss_urls = {
        "hankyoreh": "https://www.hani.co.kr/rss/",
        "chosun":    "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
        "joongang":  "https://rss.joins.com/joins_news_list.xml",
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
        "date": today.strftime("%Y-%m-%d"),
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "weather": get_weather(),
        "liturgy": get_liturgy(),
        "gospel":  get_gospel(),
        "calendar": {
            "yesterday": get_calendar_events(yesterday),
            "today":     get_calendar_events(today),
            "tomorrow":  get_calendar_events(tomorrow),
        },
        "news": {
            "hankyoreh": get_news("hankyoreh"),
            "chosun":    get_news("chosun"),
            "joongang":  get_news("joongang"),
            "donga":     get_news("donga"),
        }
    }

    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("report.json 생성 완료!")


if __name__ == "__main__":
    main()
