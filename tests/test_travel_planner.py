"""
국내 여행 추천 프로그램 단위 및 기능 검증 테스트
"""

import os
import sys
import json
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from travel_planner import validate_date
from services.place_service import _strip_html_tags, search_places_kakao, search_places_naver
from services.llm_service import _extract_json_from_text, generate_final_report


class TestTravelPlanner(unittest.TestCase):

    def test_validate_date(self):
        # 정상 날짜
        self.assertEqual(validate_date("2026-05-15"), "2026-05-15")
        self.assertEqual(validate_date("  2026-12-31  "), "2026-12-31")

        # 비정상 날짜는 SystemExit 발생
        with self.assertRaises(SystemExit):
            validate_date("2026-02-30")
        with self.assertRaises(SystemExit):
            validate_date("invalid-date")

    def test_strip_html_tags(self):
        sample = "<b>제주</b> 흑돼지 <i>맛집</i>"
        self.assertEqual(_strip_html_tags(sample), "제주 흑돼지 맛집")
        self.assertEqual(_strip_html_tags(""), "")

    def test_extract_json(self):
        # 1. 순수 JSON
        data = {"recommended_city": "제주", "weather": "맑음", "events": ["축제"], "reason": "좋음"}
        json_str = json.dumps(data)
        self.assertEqual(_extract_json_from_text(json_str), data)

        # 2. 마크다운 코드 블록으로 감싸진 JSON
        markdown_wrapped = f"```json\n{json_str}\n```"
        self.assertEqual(_extract_json_from_text(markdown_wrapped), data)

        # 3. 언어 지정 없는 마크다운 블록
        markdown_plain = f"```\n{json_str}\n```"
        self.assertEqual(_extract_json_from_text(markdown_plain), data)

    def test_place_service_auth_error_handling(self):
        # 잘못된 키로 Kakao 호출 시 crash하지 않고 error를 반환하는지 검증
        results, errors = search_places_kakao("제주", api_key="invalid_dummy_key", count=5)
        self.assertEqual(results, [])
        self.assertTrue(len(errors) > 0)
        self.assertEqual(errors[0]["type"], "AUTH_ERROR")

        # 잘못된 키로 Naver 호출 시 crash하지 않고 error를 반환하는지 검증
        results_nv, errors_nv = search_places_naver("제주", client_id="dummy_id", client_secret="dummy_secret", count=5)
        self.assertEqual(results_nv, [])
        self.assertTrue(len(errors_nv) > 0)
        self.assertEqual(errors_nv[0]["type"], "AUTH_ERROR")

    def test_fallback_report_generation(self):
        # LLM 호출 실패 시 fallback 마크다운 리포트가 정상 생성되는지 검증
        first_rec = {
            "recommended_city": "제주",
            "weather": "온화함",
            "events": ["유채꽃 축제"],
            "reason": "봄꽃을 즐기기 좋습니다."
        }
        places = [
            {"name": "제주 맛집", "address": "제주시 연동", "category": "한식"}
        ]
        errors = [
            {"step": "place_search", "type": "WARNING", "message": "테스트 경고"}
        ]
        # 환경변수 없이 generate_final_report를 호출하면 fallback_md가 정상 반환되어야 함
        report_md = generate_final_report("2026-05-15", first_rec, places, errors)
        self.assertIn("# 2026-05-15 국내 여행 추천 리포트", report_md)
        self.assertIn("## 추천 지역", report_md)
        self.assertIn("## 맛집 추천", report_md)
        self.assertIn("제주 맛집", report_md)


if __name__ == "__main__":
    unittest.main()
