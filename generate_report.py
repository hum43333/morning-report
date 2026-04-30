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
    """catholic.or.kr 성무일도 아침기도 본문 추출.
    '날 구하소서'로 시작해서 '파견'으로 끝나는 구간을 텍스트에서 직접 잘라냄.
    """
    try:
        date_str = today.strftime("%Y-%m-%d")
        headers = {"User-Agent": "Mozilla/5.0"}

        # stype=mo(아침기도) URL 직접 호출
        url = (
            f"https://maria.catholic.or.kr/mi_pr/sungmu/sungmu.asp"
            f"?menu=sungmu&sunseo=1&gomonth={date_str}&stype=mo"
        )
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        full_text = soup.get_text(separator="\n")
        lines = [l.strip() for l in full_text.splitlines()]

        # 아침기도 시작점: '날 구하소서' 가 포함된 줄
        start_idx = None
        for i, line in enumerate(lines):
            if "날 구하소서" in line:
                start_idx = i
                break

        if start_idx is None:
            # 혹시 못 찾으면 전체 텍스트에서 테이블만 추출해서 반환
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

        # 끝점: '파견'을 찾은 뒤 푸터가 나올 때 중단
        # 파견을 못 찾아도 푸터에서 중단
        found_pagen = False
        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if "파견" in lines[i]:
                found_pagen = True
            # 파견 이후 푸터/메뉴 도달 시 종료
            if found_pagen and any(kw in lines[i] for kw in [
                "이용약관", "ⓒ GoodNews", "서울대교구", "goodnews@",
                "매일미사", "가톨릭기도서", "7성사"
            ]):
                end_idx = i
                break
            # 파견 미발견 상태에서 푸터 도달 시 종료
            if not found_pagen and any(kw in lines[i] for kw in [
                "이용약관", "ⓒ GoodNews", "서울대교구", "goodnews@"
            ]):
                end_idx = i
                break

        # 불필요한 줄 제거 후 반환
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
def get_gospel():
    """catholic.or.kr 미사 페이지에서 독서/복음 스크래핑.
    - 제1독서: '제1독서' 줄부터 '화답송' 줄 직전까지
    - 제2독서: '제2독서' 줄부터 '복음 환호송' or '알렐루야' 직전까지 (있을 때만)
    - 복음:    '✠' 기호가 있는 줄부터 '주님의 말씀입니다' or '그리스도님, 찬미합니다' 까지
    """
    import re
    result = {"reading1": "", "reading2": "", "gospel": ""}
    try:
        url = "https://maria.catholic.or.kr/mi_pr/missa/missa.asp"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        # 전체 텍스트를 줄 단위로
        raw = soup.get_text(separator="\n")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]

        sections = {"reading1": [], "reading2": [], "gospel": []}
        current = None

        for line in lines:

            # ── 섹션 시작 ──────────────────────────
            if "제1독서" in line and current is None:
                current = "reading1"
                continue

            if "제2독서" in line and current in ("reading1", None):
                current = "reading2"
                continue

            # 복음 시작: ✠ 기호가 포함된 줄 (실제 복음 본문 시작)
            if "✠" in line and current != "gospel":
                current = "gospel"
                sections["gospel"].append(line)
                continue

            # ── 섹션 종료 ──────────────────────────
            if current == "reading1":
                if any(kw in line for kw in ["화답송", "알렐루야", "제2독서", "복음 환호송"]):
                    current = None
                    continue
                sections["reading1"].append(line)

            elif current == "reading2":
                if any(kw in line for kw in ["화답송", "알렐루야", "복음 환호송"]):
                    current = None
                    continue
                sections["reading2"].append(line)

            elif current == "gospel":
                sections["gospel"].append(line)
                # 복음 끝: 응답송 끝 문구
                if "그리스도님, 찬미합니다" in line or "주님의 말씀입니다" in line:
                    current = None
                    continue

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
