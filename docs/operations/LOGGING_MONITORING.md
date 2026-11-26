# Logging & Monitoring Guide

## Structured logging

API emits JSON log records โดยมี `timestamp`, `severity`, `logger`, `message`
Request records มี `correlation_id`, `method`, `route`, `status_code`, `duration_ms`

Timestamp เป็น UTC ISO 8601 และ severity เป็น Python logging level

## Correlation IDs

รับ `X-Correlation-ID` หรือ `X-Request-ID`; จำกัด 128 characters
ถ้าไม่มี ใช้ UUID
Response ส่ง `X-Correlation-ID` กลับทุก HTTP response

## Redaction

Logging code และ JSON formatter redacts authorization, password, token, api_key, cookie และ secret-like text
ไม่เก็บ full prompt หรือ conversation content เป็นค่าเริ่มต้น
Logs ต้องไม่ใช้เพื่อเก็บ PII/email/password

## Metrics

Repository ยังไม่ configure metrics collector
จึงมีเพียง instrumented HTTP duration/status/correlation logs
ห้ามตีความว่า logs คือ latency metrics หรือ availability SLO

## Authentication failures

Login ใช้ generic 401 และ rate limiting; ไม่บอกว่าบัญชีมีอยู่หรือไม่
Admin actions และ API-key revocation ยังคงอยู่ใน backend authorization
