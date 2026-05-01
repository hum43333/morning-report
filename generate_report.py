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
    """OpenWeatherMap API로 오늘 아침/낮/저녁 날씨 가져오기 (나가노 기준)"""
    if not WEATHER_API_KEY:
        return {"morning": "날씨 API 키 없음", "afternoon": "", "evening": ""}
    try:
        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?q=Gotemba,JP&appid={WEATHER_API_KEY}&units=metric&lang=kr"
        )
        r = requests.get(url, timeout=10)
        data = r.json()

        # 아침(06~09시), 낮(12~15시), 저녁(18~21시) 목표 시간
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
        found_pagen = False
        end_idx = len(lines)
        for i in range(start_idx + 1, len(lines)):
            if "파견" in lines[i]:
                found_pagen = True
            # 파견 이후 푸터/메뉴 도달 시 종료
            if found_pagen and any(kw in lines[i] for kw in [
                "이용약관", "ⓒ GoodNews", "서울대교구", "goodnews@",
                "매일미사", "가톨릭기도서", "7성사",
                "(구)성경쓰기", "미사/기도서", "말씀나누기", "성경책갈피", "내 교구"
            ]):
                end_idx = i
                break
            # 파견 미발견 상태에서 푸터 도달 시 종료
            if not found_pagen and any(kw in lines[i] for kw in [
                "이용약관", "ⓒ GoodNews", "서울대교구", "goodnews@",
                "(구)성경쓰기", "미사/기도서"
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
def get_gospel(target_date=None):
    """catholic.or.kr 미사 페이지에서 독서/복음 스크래핑.
    target_date 를 지정하면 해당 날짜의 복음을 가져옴 (기본값: 오늘).
    """
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
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")

        raw = soup.get_text(separator="\n")
        lines = [l.strip() for l in raw.splitlines() if l.strip()]

        # ── 날짜 헤더 이후부터만 파싱 ──
        date_pattern = re.compile(r"\d{4}년 \d+월 \d+일")
        body_start = 0
        for i, line in enumerate(lines):
            if date_pattern.search(line) and target_date.strftime("%Y년") in line:
                body_start = i
                break

        lines = lines[body_start:]

        sections = {"reading1": [], "reading2": [], "gospel": []}
        current = None
        reading1_done = False

        for line in lines:

            if "제1독서" in line and current is None and not reading1_done:
                current = "reading1"
                continue

            if "제2독서" in line and current is None:
                current = "reading2"
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
# ── 구글 캘린더 ────────────────────────────────────────
def get_calendar_events(date: datetime.date) -> list:
    """Google Calendar API — OAuth 토큰으로 인증해서 일정 가져오기.
    구독 캘린더(@import.calendar.google.com 포함) 모두 접근 가능.
    """
    GOOGLE_OAUTH_TOKEN = os.environ.get("GOOGLE_OAUTH_TOKEN", "")
    if not GOOGLE_OAUTH_TOKEN:
        return ["(캘린더 설정 필요: GOOGLE_OAUTH_TOKEN)"]
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        token_data = json.loads(GOOGLE_OAUTH_TOKEN)
        creds = Credentials(
            token=token_data.get("token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes"),
        )

        service = build("calendar", "v3", credentials=creds)

        # 날짜 범위 (KST 기준)
        start = datetime.datetime.combine(date, datetime.time.min).replace(tzinfo=KST).isoformat()
        end   = datetime.datetime.combine(date, datetime.time.max).replace(tzinfo=KST).isoformat()

        # CALENDAR_ID 파싱
        calendar_ids = [c.strip() for c in CALENDAR_ID.replace(';', ',').split(',') if '@' in c.strip()]
        print(f"캘린더 ID 목록 ({len(calendar_ids)}개): {calendar_ids}")

        all_events = []
        for cal_id in calendar_ids:
            try:
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=start,
                    timeMax=end,
                    singleEvents=True,
                    orderBy="startTime"
                ).execute()
                all_events.extend(events_result.get("items", []))
            except Exception:
                continue

        # 시작 시간 기준으로 정렬
        def sort_key(e):
            return e["start"].get("dateTime", e["start"].get("date", ""))

        all_events.sort(key=sort_key)

        result = []
        for e in all_events:
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
            "joongang":  get_news("joongang"),
            "donga":     get_news("donga"),
        }
    }

    with open("report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("report.json 생성 완료!")


if __name__ == "__main__":
    main()
