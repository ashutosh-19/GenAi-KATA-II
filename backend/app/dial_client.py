"""DIAL chat completion client with strict JSON extraction."""

from __future__ import annotations

import json
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()


class DialClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("DIAL_API_KEY", "")
        self.endpoint = os.getenv("DIAL_ENDPOINT", "")
        self.timeout = int(os.getenv("DIAL_TIMEOUT_SECONDS", "45"))

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.endpoint)

    def chat_json(self, prompt: str, temperature: float = 0.0) -> dict:
        if not self.available:
            raise RuntimeError("DIAL credentials are not configured")

        payload = {
            "temperature": temperature,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only valid JSON. Do not add markdown code fences.",
                },
                {"role": "user", "content": prompt},
            ],
        }

        headers = {"Api-Key": self.api_key, "Content-Type": "application/json"}

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return self._extract_json(content)

    def chat_text(self, prompt: str, temperature: float = 0.0) -> str:
        if not self.available:
            raise RuntimeError("DIAL credentials are not configured")

        payload = {
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        headers = {"Api-Key": self.api_key, "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _extract_json(raw: str) -> dict:
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, flags=re.DOTALL)
        if fenced:
            return json.loads(fenced.group(1))

        bracketed = re.search(r"(\{.*\})", raw, flags=re.DOTALL)
        if bracketed:
            return json.loads(bracketed.group(1))

        raise ValueError("Failed to parse JSON from model response")
