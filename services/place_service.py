"""
지도 및 장소 검색 API 연동 서비스
- Kakao Local API 및 Naver Local Search API 지원
- 키워드 기반 맛집 5곳 검색
- 401/403 인증 오류, 네트워크 오류, 0건 검색 결과에 대한 무중단 예외 처리 (Graceful Degradation)
"""

import os
import re
import requests
from typing import List, Dict, Any, Tuple


def _strip_html_tags(text: str) -> str:
    """HTML 태그 제거 (네이버 검색 결과의 <b> 태그 등)"""
    if not text:
        return ""
    clean = re.compile("<.*?>")
    return re.sub(clean, "", text)


def search_places_kakao(city: str, api_key: str, count: int = 5) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Kakao Local API를 사용한 장소(맛집) 검색
    """
    errors: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    query = f"{city} 맛집"
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {api_key.strip()}"}
    params = {"query": query, "size": count}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code in (401, 403):
            errors.append({
                "step": "place_search",
                "provider": "kakao",
                "type": "AUTH_ERROR",
                "message": f"HTTP {response.status_code}: Kakao REST API 키 인증에 실패했습니다."
            })
            return results, errors

        response.raise_for_status()
        data = response.json()
        documents = data.get("documents", [])

        if not documents:
            errors.append({
                "step": "place_search",
                "provider": "kakao",
                "type": "EMPTY_RESULT",
                "message": f"0 results for query={query}"
            })
            return results, errors

        for doc in documents:
            results.append({
                "city": city,
                "name": doc.get("place_name", "").strip(),
                "address": doc.get("road_address_name") or doc.get("address_name", ""),
                "category": doc.get("category_name", ""),
                "url": doc.get("place_url", ""),
                "x": float(doc.get("x", 0)) if doc.get("x") else None,
                "y": float(doc.get("y", 0)) if doc.get("y") else None
            })

    except requests.exceptions.RequestException as e:
        errors.append({
            "step": "place_search",
            "provider": "kakao",
            "type": "NETWORK_ERROR",
            "message": f"카카오 장소 검색 네트워크 오류: {str(e)}"
        })
    except Exception as e:
        errors.append({
            "step": "place_search",
            "provider": "kakao",
            "type": "UNKNOWN_ERROR",
            "message": f"카카오 응답 처리 중 오류: {str(e)}"
        })

    return results, errors


def search_places_naver(city: str, client_id: str, client_secret: str, count: int = 5) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Naver Local Search API를 사용한 장소(맛집) 검색
    """
    errors: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []
    query = f"{city} 맛집"
    url = "https://openapi.naver.com/v1/search/local.json"
    headers = {
        "X-Naver-Client-Id": client_id.strip(),
        "X-Naver-Client-Secret": client_secret.strip()
    }
    params = {"query": query, "display": count, "sort": "comment"}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code in (401, 403):
            errors.append({
                "step": "place_search",
                "provider": "naver",
                "type": "AUTH_ERROR",
                "message": f"HTTP {response.status_code}: Naver API Client ID/Secret 인증에 실패했습니다."
            })
            return results, errors

        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])

        if not items:
            errors.append({
                "step": "place_search",
                "provider": "naver",
                "type": "EMPTY_RESULT",
                "message": f"0 results for query={query}"
            })
            return results, errors

        for item in items:
            # Naver mapx, mapy are in KATECH coordinates or integers
            results.append({
                "city": city,
                "name": _strip_html_tags(item.get("title", "")),
                "address": item.get("roadAddress") or item.get("address", ""),
                "category": item.get("category", ""),
                "url": item.get("link", ""),
                "x": item.get("mapx"),
                "y": item.get("mapy")
            })

    except requests.exceptions.RequestException as e:
        errors.append({
            "step": "place_search",
            "provider": "naver",
            "type": "NETWORK_ERROR",
            "message": f"네이버 장소 검색 네트워크 오류: {str(e)}"
        })
    except Exception as e:
        errors.append({
            "step": "place_search",
            "provider": "naver",
            "type": "UNKNOWN_ERROR",
            "message": f"네이버 응답 처리 중 오류: {str(e)}"
        })

    return results, errors


def search_restaurants(city: str, count: int = 5) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    환경변수에 설정된 지도 API 제공자에 따라 맛집 검색을 수행합니다.
    우선순위: KAKAO_REST_API_KEY -> NAVER_CLIENT_ID / NAVER_CLIENT_SECRET
    """
    kakao_key = os.getenv("KAKAO_REST_API_KEY")
    naver_id = os.getenv("NAVER_CLIENT_ID")
    naver_secret = os.getenv("NAVER_CLIENT_SECRET")

    if kakao_key and kakao_key.strip() and kakao_key != "your_kakao_rest_api_key_here":
        return search_places_kakao(city, kakao_key, count)
    elif naver_id and naver_secret and naver_id.strip() and naver_secret.strip() and naver_id != "your_naver_client_id_here":
        return search_places_naver(city, naver_id, naver_secret, count)
    else:
        # API 키가 설정되지 않은 경우
        return [], [{
            "step": "place_search",
            "type": "KEY_MISSING",
            "message": "지도/장소 API 키가 .env에 설정되어 있지 않습니다 (KAKAO_REST_API_KEY 또는 NAVER_CLIENT_ID/SECRET 필요)."
        }]
