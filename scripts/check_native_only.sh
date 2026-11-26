#!/bin/bash
echo "🛡️ ตรวจสอบนโยบาย Native-Only..."
VIOLATIONS=$(grep -rniE "huggingface_hub|snapshot_download|from_pretrained|openai|anthropic" apps/core/native/ tools/train_nagi_*.py 2>/dev/null)

if [ -n "$VIOLATIONS" ]; then
    echo "❌ พบการละเมิด Native-Only Policy!"
    echo "$VIOLATIONS"
    exit 1
else
    echo "✅ ผ่าน: ไม่พบการใช้โมเดลหรือ API ภายนอก"
    exit 0
fi
