"""
LLM API 연동 서비스
- Google Gemini API 및 OpenAI API REST 통신 지원
- 1차 여행지 추천 (JSON 구조화 출력 및 최대 1회 재시도)
- 2차 최종 마크다운 리포트 생성
"""

import os
import json
import re
import requests
from typing import Dict, Any, Tuple, Optional, List


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """
    LLM 응답 텍스트에서 마크다운 코드 블록(```json ... ```)을 제거하고 JSON으로 파싱합니다.
    """
    text = text.strip()
    # ```json ... ``` 또는 ``` ... ``` 마크다운 블록 추출
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        clean_text = match.group(1).strip()
    else:
        clean_text = text

    return json.loads(clean_text)


def _call_gemini_api(api_key: str, prompt: str, as_json: bool = False) -> str:
    """
    Google Gemini REST API 호출
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key.strip()}"
    headers = {"Content-Type": "application/json"}
    payload: Dict[str, Any] = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }
    if as_json:
        payload["generationConfig"] = {
            "responseMimeType": "application/json"
        }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code in (401, 403):
        raise PermissionError(f"Gemini API 인증 실패 (HTTP {response.status_code}). API 키를 확인하세요.")
    response.raise_for_status()

    data = response.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini API 응답에 candidate 결과가 없습니다.")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("Gemini API 응답 본문이 비어 있습니다.")

    return parts[0].get("text", "")


def _call_openai_api(api_key: str, prompt: str, as_json: bool = False) -> str:
    """
    OpenAI Chat Completions REST API 호출
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json"
    }
    payload: Dict[str, Any] = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a professional domestic travel assistant in South Korea."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    if as_json:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code in (401, 403):
        raise PermissionError(f"OpenAI API 인증 실패 (HTTP {response.status_code}). API 키를 확인하세요.")
    response.raise_for_status()

    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("OpenAI API 응답에 choices 결과가 없습니다.")

    return choices[0].get("message", {}).get("content", "")


def call_llm(prompt: str, as_json: bool = False) -> str:
    """
    설정된 환경변수에 따라 Gemini 또는 OpenAI API를 호출합니다.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if gemini_key and gemini_key.strip() and gemini_key != "your_gemini_api_key_here":
        return _call_gemini_api(gemini_key, prompt, as_json=as_json)
    elif openai_key and openai_key.strip() and openai_key != "your_openai_api_key_here":
        return _call_openai_api(openai_key, prompt, as_json=as_json)
    else:
        raise ValueError("LLM API 키가 설정되지 않았습니다. .env 파일에 GEMINI_API_KEY 또는 OPENAI_API_KEY를 설정하세요.")


def get_first_recommendation(date_str: str, multi_cities: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    1차 여행지 추천 생성 (LLM 호출 및 JSON 파싱, 실패 시 1회 재시도)
    """
    errors: List[Dict[str, Any]] = []

    if multi_cities:
        prompt = f"""
당신은 한국 국내 여행 전문 컨설턴트입니다.
여행 날짜는 '{date_str}'입니다.
해당 날짜(계절, 날씨 특성, 시즌 축제 등)에 여행하기 가장 좋은 대한민국 국내 여행지 2~3곳을 추천해주세요.

반드시 아래 JSON 스키마를 만족하는 유효한 JSON 객체 하나만 출력하세요. 다른 안내 문구는 일절 포함하지 마세요.

{{
  "recommended_cities": ["도시1", "도시2"],
  "recommended_city": "도시1",
  "weather": "{date_str} 시기의 일반적인 날씨 요약 (기온, 강수, 옷차림 팁)",
  "events": ["해당 시기 지역 축제/행사 1~3개"],
  "reason": "해당 시기에 이 도시들을 추천하는 종합적인 이유 (2~4문장)"
}}
"""
    else:
        prompt = f"""
당신은 한국 국내 여행 전문 컨설턴트입니다.
여행 날짜는 '{date_str}'입니다.
해당 날짜(계절, 날씨 특성, 시즌 축제 등)에 여행하기 가장 좋은 대한민국 국내 도시 1곳을 추천해주세요.

반드시 아래 JSON 스키마를 만족하는 유효한 JSON 객체 하나만 출력하세요. 다른 안내 문구는 일절 포함하지 마세요.

{{
  "recommended_city": "추천 도시 이름 (예: 제주, 강릉, 여수 등)",
  "weather": "{date_str} 시기의 일반적인 날씨 요약 (기온, 바람, 옷차림 팁 등)",
  "events": ["해당 시기 지역 행사 또는 축제 후보 1~3개"],
  "reason": "해당 날짜에 이 도시를 추천하는 구체적인 근거 (2~4문장)"
}}
"""

    # 1차 시도
    raw_response = ""
    try:
        raw_response = call_llm(prompt, as_json=True)
        parsed_json = _extract_json_from_text(raw_response)

        # 필수 키 검증
        required_keys = ["recommended_city", "weather", "events", "reason"]
        for key in required_keys:
            if key not in parsed_json:
                raise KeyError(f"필수 키 '{key}'가 누락되었습니다.")

        return parsed_json, errors

    except Exception as first_error:
        errors.append({
            "step": "llm_recommendation_attempt_1",
            "type": "PARSE_ERROR" if isinstance(first_error, (json.JSONDecodeError, KeyError)) else "API_ERROR",
            "message": f"1차 시도 실패: {str(first_error)}"
        })

        # 재시도 1회 수행
        retry_prompt = f"""
이전 출력에서 JSON 파싱 오류가 발생했습니다.
반드시 마크다운이나 부가 설명 없이 오직 순수한 JSON 문자열만 출력해야 합니다.

여행 날짜: {date_str}
필수 포함 키:
- "recommended_city": (문자열, 예: "제주")
- "weather": (문자열, 날씨 요약)
- "events": (문자열 배열, 행사 1~3개)
- "reason": (문자열, 추천 이유 2~4문장)
"""
        try:
            raw_response = call_llm(retry_prompt, as_json=True)
            parsed_json = _extract_json_from_text(raw_response)
            return parsed_json, errors
        except Exception as retry_error:
            errors.append({
                "step": "llm_recommendation_attempt_2",
                "type": "FATAL_ERROR",
                "message": f"재시도 실패: {str(retry_error)}"
            })
            # 최후의 fallback JSON 반환 (프로그램 중단 방지)
            fallback_json = {
                "recommended_city": "제주",
                "weather": "날씨 정보 파싱 실패",
                "events": ["행사 정보 없음"],
                "reason": "LLM 응답을 파싱하지 못하여 기본 추천 지역으로 대체되었습니다."
            }
            return fallback_json, errors


def generate_final_report(
    date_str: str,
    first_recommendation: Dict[str, Any],
    places: List[Dict[str, Any]],
    errors: List[Dict[str, Any]]
) -> str:
    """
    1차 추천 + 맛집 검색 결과 + 에러 목록을 기반으로 최종 마크다운 리포트 생성
    """
    prompt = f"""
당신은 여행 리포트 전문 작성가입니다.
아래 제공된 '여행 날짜', '1차 추천 결과(JSON)', '맛집 검색 결과(JSON)', '발생한 오류 목록(JSON)'을 종합하여,
여행자를 위한 정갈하고 유익한 최종 Markdown 여행 리포트를 작성해주세요.

[입력 데이터]
- 여행 날짜: {date_str}
- 1차 추천 정보:
{json.dumps(first_recommendation, ensure_ascii=False, indent=2)}

- 맛집 검색 결과:
{json.dumps(places, ensure_ascii=False, indent=2)}

- 시스템 오류 목록:
{json.dumps(errors, ensure_ascii=False, indent=2)}

[작성 가이드라인]
반드시 다음 마크다운 섹션 구조를 포함하여 작성하세요:
1. # {date_str} 국내 여행 추천 리포트
2. ## 추천 지역 (지역명 및 한 줄 테마)
3. ## 추천 이유 (계절적/상황적 매력)
4. ## 날씨 요약 (기온, 체감 날씨, 추천 복장)
5. ## 행사/축제 (진행 예정인 축제나 즐길 거리 목록)
6. ## 맛집 추천:
   - 맛집 데이터가 있으면 상호명, 카테고리, 주소, 링크(있을 경우)를 마크다운 목록이나 표로 깔끔하게 정리.
   - 맛집 데이터가 0건이거나 비어있으면 반드시 "데이터 없음 (장소 검색 결과 0건 또는 검색 실패)"로 명확히 표기.
7. ## 1일 일정 제안 (오전 / 점심 및 오후 / 저녁 코스)
8. ## 오류 요약 (errors):
   - 오류가 있으면 발생 단계와 내용을 요약. 오류가 전혀 없으면 "발생한 오류가 없습니다 (정상 처리 완료)"로 표기.

친절하고 격려하는 여행 플래너의 어조로 깔끔하게 마크다운으로만 출력하세요.
"""

    try:
        report_text = call_llm(prompt, as_json=False)
        # 만약 ```markdown ... ``` 으로 감싸져 있다면 래핑 제거
        match = re.search(r"```(?:markdown)?\s*([\s\S]*?)\s*```", report_text.strip())
        if match:
            return match.group(1).strip()
        return report_text.strip()
    except Exception as e:
        # LLM 리포트 생성 실패 시 Fallback 마크다운 리포트 자체 생성
        fallback_md = f"""# {date_str} 국내 여행 추천 리포트

## 추천 지역
- {first_recommendation.get('recommended_city', '알 수 없음')}

## 추천 이유
{first_recommendation.get('reason', '정보 없음')}

## 날씨 요약
{first_recommendation.get('weather', '정보 없음')}

## 행사/축제
"""
        for event in first_recommendation.get("events", []):
            fallback_md += f"- {event}\n"

        fallback_md += "\n## 맛집 추천\n"
        if places:
            for p in places:
                fallback_md += f"- **{p.get('name')}** ({p.get('category', '음식점')}): {p.get('address', '')}\n"
        else:
            fallback_md += "- 데이터 없음 (장소 검색 결과 0건)\n"

        fallback_md += f"""
## 1일 일정 제안
- 오전: {first_recommendation.get('recommended_city')} 도착 및 주요 명소 산책
- 오후: 현지 대표 명소 탐방 및 카페 방문
- 저녁: 특산물 식사 및 야경 감상

## 오류 요약 (errors)
- 리포트 자동 생성 중 오류 발생: {str(e)}
"""
        return fallback_md
