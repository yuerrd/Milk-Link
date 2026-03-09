-- 完整数据库升级 SQL
-- 从 b3f1a8e2c047 手动应用缺失的更改并升级到 360b08025977

-- ==========================================
-- 第一步：添加 record_type 字段（b3f1a8e2c047 的实际内容）
-- ==========================================

-- 检查 record_type 是否已存在
SET @exist_record_type := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'milklink' AND TABLE_NAME = 'feeding_records' AND COLUMN_NAME = 'record_type');

-- 添加 record_type 列（如果不存在）
SET @sql_add_record_type := IF(@exist_record_type = 0, 
    'ALTER TABLE feeding_records ADD COLUMN record_type ENUM(''milk'', ''solid'') NOT NULL DEFAULT ''milk''',
    'SELECT ''record_type already exists'' AS info');

PREPARE stmt FROM @sql_add_record_type;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ==========================================
-- 第二步：添加 amount_value 和 unit 字段（360b08025977）
-- ==========================================

-- 检查 amount_value 是否已存在
SET @exist_amount_value := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'milklink' AND TABLE_NAME = 'feeding_records' AND COLUMN_NAME = 'amount_value');

-- 添加 amount_value 列
SET @sql_add_amount_value := IF(@exist_amount_value = 0,
    'ALTER TABLE feeding_records ADD COLUMN amount_value INT NULL',
    'SELECT ''amount_value already exists'' AS info');

PREPARE stmt FROM @sql_add_amount_value;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- 检查 unit 是否已存在
SET @exist_unit := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_SCHEMA = 'milklink' AND TABLE_NAME = 'feeding_records' AND COLUMN_NAME = 'unit');

-- 添加 unit 列
SET @sql_add_unit := IF(@exist_unit = 0,
    'ALTER TABLE feeding_records ADD COLUMN unit ENUM(''ml'', ''g'') NULL',
    'SELECT ''unit already exists'' AS info');

PREPARE stmt FROM @sql_add_unit;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ==========================================
-- 第三步：数据迁移
-- ==========================================

-- 从 amount_ml 复制数据到 amount_value
UPDATE feeding_records SET amount_value = amount_ml WHERE amount_value IS NULL;

-- 根据 record_type 设置 unit
UPDATE feeding_records SET unit = 'ml' WHERE record_type = 'milk' AND unit IS NULL;
UPDATE feeding_records SET unit = 'g' WHERE record_type = 'solid' AND unit IS NULL;

-- ==========================================
-- 第四步：设置 NOT NULL 约束
-- ==========================================

-- 设置 amount_value 为 NOT NULL
ALTER TABLE feeding_records MODIFY COLUMN amount_value INT NOT NULL;

-- 设置 unit 为 NOT NULL
ALTER TABLE feeding_records MODIFY COLUMN unit ENUM('ml', 'g') NOT NULL;

-- ==========================================
-- 第五步：更新迁移版本
-- ==========================================

-- 更新到最新版本
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('360b08025977');

-- ==========================================
-- 验证结果
-- ==========================================

SELECT '=== 迁移完成，当前版本 ===' AS info;
SELECT * FROM alembic_version;

SELECT '=== 更新后的表结构 ===' AS info;
DESCRIBE feeding_records;

SELECT '=== 数据示例 ===' AS info;
SELECT id, device_id, amount_value, unit, record_type, period, fed_at 
FROM feeding_records 
ORDER BY fed_at DESC 
LIMIT 3;
