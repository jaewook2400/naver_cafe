# Playwright 공식 Python 이미지 사용 (브라우저 포함)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 스크립트 복사
COPY playwright_getIds_auto.py .

# auth.json은 실행 시 볼륨으로 마운트

# 기본 환경변수
ENV START=0
ENV END=100
ENV WORKER=1
ENV OUTPUT_DIR=/app/output

CMD ["python", "playwright_getIds_auto.py"]
