#!/usr/bin/env python3
"""
국내 여행 추천 CLI 프로그램 (Domestic Travel Planner)
- LLM API(Gemini/OpenAI)와 지도/장소 검색 API(Kakao/Naver)를 결합한 여행 일정 및 맛집 추천
"""

import os
import sys
import io

# Windows 콘솔 한글 깨짐 방지
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

import json
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# 로컬 패키지 모듈 import
from services.llm_service import get_first_recommendation, generate_final_report
from services.place_service import search_restaurants


def validate_date(date_string: str) -> str:
    """날짜 형식(YYYY-MM-DD) 유효성을 검사합니다."""
    try:
        parsed = datetime.strptime(date_string.strip(), "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        print(f"\n[오류] 올바르지 않은 날짜 형식입니다: '{date_string}'")
        print("올바른 사용법:")
        print("  python travel_planner.py --date \"YYYY-MM-DD\" (예: python travel_planner.py --date \"2026-05-15\")\n")
        sys.exit(1)


def check_api_keys() -> None:
    """필수 API 키가 설정되어 있는지 사전에 검증합니다."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    has_valid_gemini = gemini_key and gemini_key.strip() and gemini_key != "your_gemini_api_key_here"
    has_valid_openai = openai_key and openai_key.strip() and openai_key != "your_openai_api_key_here"

    if not (has_valid_gemini or has_valid_openai):
        print("\n" + "=" * 70)
        print("[오류] LLM API 키가 설정되지 않았습니다!")
        print("=" * 70)
        print("프로그램을 실행하려면 '.env' 파일에 유효한 API 키를 설정해야 합니다.")
        print("\n[설정 방법]")
        print("1. 프로젝트 루트의 '.env.example' 파일을 복사하여 '.env' 파일을 생성합니다:")
        print("   cp .env.example .env   (Windows의 경우: copy .env.example .env)")
        print("2. 생성된 '.env' 파일에 발급받은 API 키를 입력합니다:")
        print("   GEMINI_API_KEY=AIzaSy... (Google AI Studio 발급)")
        print("   또는")
        print("   OPENAI_API_KEY=sk-...    (OpenAI Platform 발급)")
        print("=" * 70 + "\n")
        sys.exit(1)


def main():
    # .env 파일 로드
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="국내 여행 추천 CLI 프로그램 (LLM + 지도 검색 API 연동)",
        usage="python travel_planner.py --date \"YYYY-MM-DD\" [옵션]"
    )
    # -date 및 --date 둘 다 지원
    parser.add_argument(
        "-date", "--date", "-d",
        dest="date",
        required=True,
        help="여행 날짜 (필수, 형식: YYYY-MM-DD)"
    )
    # 보너스 기능: 캐싱 무시 옵션
    parser.add_argument(
        "--force", "--no-cache",
        action="store_true",
        help="기존 캐시 파일이 있더라도 무시하고 API를 새로 호출합니다."
    )
    # 보너스 기능: 복수 지역 추천 옵션
    parser.add_argument(
        "--multi",
        action="store_true",
        help="단일 도시가 아닌 복수 지역(2~3곳)을 추천받습니다."
    )

    args = parser.parse_args()
    date_str = validate_date(args.date)

    # 결과 저장 디렉토리 준비
    results_dir = Path("results")
    results_dir.mkdir(parents=True, exist_ok=True)

    raw_json_path = results_dir / f"{date_str}_travel_plan.json"
    report_md_path = results_dir / f"{date_str}_travel_plan.md"

    # [보너스 과제] 캐싱 확인
    if not args.force and raw_json_path.exists() and report_md_path.exists():
        print(f"\n[캐시 확인] {date_str} 날짜의 추천 결과가 이미 존재합니다.")
        print(f"  - 원본 데이터: {raw_json_path}")
        print(f"  - 최종 리포트: {report_md_path}")
        print("  (새로 생성하려면 --force 옵션을 추가하여 실행하세요.)\n")
        return

    # 신규 호출 시 필수 키 검증
    check_api_keys()

    print(f"\n==================================================")
    print(f"  국내 여행 플래너 실행: {date_str}")
    print(f"==================================================")

    collected_errors = []

    # -------------------------------------------------------------
    # [1/3] 1차 추천 생성 (LLM)
    # -------------------------------------------------------------
    print("\n[1/3] 1차 추천 생성 중(LLM)...")
    try:
        first_rec, rec_errors = get_first_recommendation(date_str, multi_cities=args.multi)
        collected_errors.extend(rec_errors)
        recommended_city = first_rec.get("recommended_city", "미상")
        print(f"  - recommended_city: \"{recommended_city}\"")
        if args.multi and "recommended_cities" in first_rec:
            print(f"  - recommended_cities: {first_rec.get('recommended_cities')}")
    except Exception as e:
        print(f"  - [오류] 1차 추천 중 심각한 오류 발생: {str(e)}")
        first_rec = {
            "recommended_city": "추천 실패",
            "weather": "날씨 정보 없음",
            "events": [],
            "reason": f"추천 생성에 실패하였습니다: {str(e)}"
        }
        collected_errors.append({"step": "1st_recommendation", "type": "FATAL", "message": str(e)})

    # -------------------------------------------------------------
    # [2/3] 맛집 검색 (지도/장소 API)
    # -------------------------------------------------------------
    print("\n[2/3] 맛집 검색 중(지도/장소 API)...")
    raw_city = first_rec.get("recommended_city", "")
    target_cities = [raw_city] if raw_city and raw_city != "추천 실패" else []
    if args.multi and "recommended_cities" in first_rec:
        target_cities = [c for c in first_rec.get("recommended_cities", []) if c and c != "추천 실패"]

    all_places = []
    for city in target_cities:
        places, place_errors = search_restaurants(city, count=5)
        collected_errors.extend(place_errors)
        all_places.extend(places)

    if all_places:
        print(f"  - 맛집 {len(all_places)}곳 검색 완료")
    else:
        # 에러 내역에 따른 안내
        recent_err = collected_errors[-1] if collected_errors else {}
        err_msg = recent_err.get("message", "검색 결과 0건")
        print(f"  - 맛집 검색 결과 없음 ({err_msg})")
        print(f"  - 맛집 섹션은 '데이터 없음'으로 처리하고 다음 단계로 진행합니다.")

    # -------------------------------------------------------------
    # [3/3] 최종 리포트 생성 (LLM)
    # -------------------------------------------------------------
    print("\n[3/3] 최종 리포트 생성 중(LLM)...")
    try:
        final_report_md = generate_final_report(date_str, first_rec, all_places, collected_errors)
        print("  - 리포트 생성 완료")
    except Exception as e:
        print(f"  - [오류] 최종 리포트 생성 실패: {str(e)}")
        final_report_md = f"# {date_str} 국내 여행 추천 리포트\n\n리포트 생성 중 오류 발생: {str(e)}"
        collected_errors.append({"step": "final_report", "type": "FATAL", "message": str(e)})

    # -------------------------------------------------------------
    # 결과 파일 저장
    # -------------------------------------------------------------
    # 1. 원본 데이터 JSON 저장
    raw_data = {
        "date": date_str,
        "first_recommendation": first_rec,
        "places": all_places,
        "errors": collected_errors
    }
    with open(raw_json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)

    # 2. 최종 마크다운 리포트 저장
    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write(final_report_md)

    print("\n" + "=" * 50)
    print(f"완료! 결과물이 성공적으로 저장되었습니다:")
    print(f"  - 원본 JSON: {raw_json_path}")
    print(f"  - 여행 리포트: {report_md_path}")
    print("=" * 50 + "\n")


if __name__ == "__main__":
    main()
