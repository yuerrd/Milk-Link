#!/bin/bash
# Milk-Link 服务器数据库修复脚本
# 用于清理错误的 alembic 迁移版本

set -e

echo "=== Milk-Link 数据库修复脚本 ==="

# 数据库连接信息（从 .env 中提取）
DB_HOST="43.138.35.101"
DB_USER="root"
DB_PASS="Yuerrd@123"
DB_NAME="milklink"

echo "2. 清理错误的迁移记录..."
docker run -i --rm mysql:8.0 mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASS" "$DB_NAME" << 'EOF'
-- 清理 alembic_version 表
DELETE FROM alembic_version WHERE version_num = 'c1234567890a';

-- 重置到上一个正确版本
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('b3f1a8e2c047');

-- 删除可能存在的错误列
SET @exist_amount_value := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'milklink' AND TABLE_NAME = 'feeding_records' AND COLUMN_NAME = 'amount_value');
SET @exist_unit := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'milklink' AND TABLE_NAME = 'feeding_records' AND COLUMN_NAME = 'unit');

SET @sql_amount := IF(@exist_amount_value > 0, 'ALTER TABLE feeding_records DROP COLUMN amount_value;', 'SELECT 1;');
SET @sql_unit := IF(@exist_unit > 0, 'ALTER TABLE feeding_records DROP COLUMN unit;', 'SELECT 1;');

PREPARE stmt_amount FROM @sql_amount;
EXECUTE stmt_amount;
DEALLOCATE PREPARE stmt_amount;

PREPARE stmt_unit FROM @sql_unit;
EXECUTE stmt_unit;
DEALLOCATE PREPARE stmt_unit;

-- 显示当前状态
SELECT * FROM alembic_version;
DESCRIBE feeding_records;
EOF

echo ""
echo "=== 修复完成 ==="
echo "请检查日志确认迁移成功执行"
echo "访问 http://43.138.35.101:8000/health 验证服务"
