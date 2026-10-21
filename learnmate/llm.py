"""The ONLY file that talks to an AI provider. Any OpenAI-compatible endpoint works (Gemini, OpenAI, Groq, ...)."""
import hashlib
import time
from collections import OrderedDict

import requests

import config
from errors import UserError

_cache = OrderedDict()  # identical request -> saved answer (saves money)


def get_api_key(api_key=None):
    return api_key or config.LLM_API_KEY"""The ONLY file that talks to an AI provider. Any OpenAI-compatible endpoint works (Gemini, OpenAI, Groq, ...)."""
import hashlib
import time
from collections import OrderedDict

import requests

import config
from errors import UserError

_cache = OrderedDict()  # identical request -> saved answer (saves money)


def get_api_key(api_key=None):
    return api_key or config.LLM_API_KEY


def is_live(api_key=None):
    key = get_api_key(api_key)
    return bool(key) and not config.FORCE_DEMO


def complete(system, user, max_tokens, api_key=None, base_url=None, model=None):
    effective_key = get_api_key(api_key)
    if not effective_key:
        raise UserError("no_api_key", "No AI API key configured.", "Enter your API key in the header.", 400)
    
    effective_model = model or config.LLM_MODEL
    effective_base_url = (base_url or config.LLM_BASE_URL).rstrip("/")
    
    # Secure cache key factoring in endpoint, model, tokens, system, and user payload
    key = hashlib.sha256(f"{effective_base_url}|{effective_model}|{max_tokens}|{system}|{user}".encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
        
    # Calibrated temperature: precise for structured/educational grounding (0.7)
    body = {
        "model": effective_model,
        "temperature": 0.7,
        "top_p": 0.95,
        "max_tokens": min(max_tokens, 4096),
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
    }
    url = f"{effective_base_url}/chat/completions"
    
    r = None
    max_attempts = 2                       # was 4: 4 x 75s retries outlasted Render's ~100s limit -> 'Request failed'
    deadline = time.monotonic() + 80       # never keep the user waiting longer than this in total
    for attempt in range(max_attempts):
        try:
            r = requests.post(url, json=body, timeout=(10, 45), headers={"Authorization": f"Bearer {effective_key}"})
        except requests.RequestException:
            if attempt < max_attempts - 1 and time.monotonic() < deadline - 50:
                time.sleep(1)
                continue
            raise UserError("ai_unreachable", "The AI service could not be reached.", f"Check your internet or endpoint URL: {effective_base_url}", 502)
            
        if r.status_code == 429 and attempt < max_attempts - 1:
            wait_time = 2 * (attempt + 1)
            try:
                hdr = r.headers.get("Retry-After")
                if isinstance(hdr, str) and hdr.isdigit():
                    wait_time = float(hdr)
            except Exception:
                pass
            time.sleep(min(wait_time, 8))
            continue
        elif r.status_code == 503 and attempt < max_attempts - 1:
            time.sleep(2)
            continue
        break
        
    if r.status_code == 429:
        detail = r.text[:150].replace(effective_key, "***")
        raise UserError("ai_rate_limit", "Rate limit reached (429). The model provider is temporarily busy.",
                        f"Details: {detail}", 429)
                        
    if r.status_code != 200:
        detail = r.text[:150].replace(effective_key, "***")  # never echo the key
        raise UserError("ai_error", f"The AI service returned an error ({r.status_code}).",
                        f"Check your API Key, base URL ({effective_base_url}), or model ({effective_model}). Details: {detail}", 502)
    try:
        msg = r.json()["choices"][0]["message"]
        # NVIDIA / reasoning models can provide response in 'content' or 'reasoning_content'
        text = (msg.get("content") or "").strip()  # never show the model's hidden reasoning as the answer
        if not text:
            raise ValueError("empty content")
    except (KeyError, IndexError, ValueError, AttributeError):
        raise UserError("ai_empty", "The AI returned an empty answer.", "Try again.", 502)
        
    _cache[key] = text
    if len(_cache) > config.CACHE_SIZE:
        _cache.popitem(last=False)
    return text



def is_live(api_key=None):
    key = get_api_key(api_key)
    return bool(key) and not config.FORCE_DEMO


def complete(system, user, max_tokens, api_key=None, base_url=None, model=None):
    effective_key = get_api_key(api_key)
    if not effective_key:
        raise UserError("no_api_key", "No AI API key configured.", "Enter your API key in the header.", 400)
    
    effective_model = model or config.LLM_MODEL
    effective_base_url = (base_url or config.LLM_BASE_URL).rstrip("/")
    
    # Secure cache key factoring in endpoint, model, tokens, system, and user payload
    key = hashlib.sha256(f"{effective_base_url}|{effective_model}|{max_tokens}|{system}|{user}".encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
        
    # Calibrated temperature: precise for structured/educational grounding (0.7)
    body = {
        "model": effective_model,
        "temperature": 0.7,
        "top_p": 0.95,
        "max_tokens": min(max_tokens, 4096),
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
    }
    url = f"{effective_base_url}/chat/completions"
    
    r = None
    max_attempts = 4
    for attempt in range(max_attempts):
        try:
            r = requests.post(url, json=body, timeout=75, headers={"Authorization": f"Bearer {effective_key}"})
        except requests.RequestException:
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            raise UserError("ai_unreachable", "The AI service could not be reached.", f"Check your internet or endpoint URL: {effective_base_url}", 502)
            
        if r.status_code == 429 and attempt < max_attempts - 1:
            wait_time = 2 * (attempt + 1)
            try:
                hdr = r.headers.get("Retry-After")
                if isinstance(hdr, str) and hdr.isdigit():
                    wait_time = float(hdr)
            except Exception:
                pass
            time.sleep(min(wait_time, 8))
            continue
        elif r.status_code == 503 and attempt < max_attempts - 1:
            time.sleep(2)
            continue
        break
        
    if r.status_code == 429:
        detail = r.text[:150].replace(effective_key, "***")
        raise UserError("ai_rate_limit", "Rate limit reached (429). The model provider is temporarily busy.",
                        f"Details: {detail}", 429)
                        
    if r.status_code != 200:
        detail = r.text[:150].replace(effective_key, "***")  # never echo the key
        raise UserError("ai_error", f"The AI service returned an error ({r.status_code}).",
                        f"Check your API Key, base URL ({effective_base_url}), or model ({effective_model}). Details: {detail}", 502)
    try:
        msg = r.json()["choices"][0]["message"]
        # NVIDIA / reasoning models can provide response in 'content' or 'reasoning_content'
        text = (msg.get("content") or msg.get("reasoning_content") or "").strip()
        if not text:
            raise ValueError("empty content")
    except (KeyError, IndexError, ValueError, AttributeError):
        raise UserError("ai_empty", "The AI returned an empty answer.", "Try again.", 502)
        
    _cache[key] = text
    if len(_cache) > config.CACHE_SIZE:
        _cache.popitem(last=False)
    return text
