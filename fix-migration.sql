-- Milk-Link 数据库修复 SQL
-- 清理错误的迁移记录并重置到正确版本

-- 清理错误的迁移记录
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
SELECT '=== 当前迁移版本 ===' AS info;
SELECT * FROM alembic_version;

SELECT '=== feeding_records 表结构 ===' AS info;
DESCRIBE feeding_records;
