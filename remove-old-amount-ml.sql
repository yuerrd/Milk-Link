-- 删除旧的 amount_ml 字段
-- 因为现在使用 amount_value 和 unit 代替

-- 检查字段是否存在
SET @exist_amount_ml := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'milklink' AND TABLE_NAME = 'feeding_records' AND COLUMN_NAME = 'amount_ml');

-- 删除 amount_ml 字段
SET @sql_drop_amount_ml := IF(@exist_amount_ml > 0,
    'ALTER TABLE feeding_records DROP COLUMN amount_ml',
    'SELECT ''amount_ml already removed'' AS info');

PREPARE stmt FROM @sql_drop_amount_ml;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 验证结果
SELECT '=== 更新后的表结构 ===' AS info;
DESCRIBE feeding_records;
