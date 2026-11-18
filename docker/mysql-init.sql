CREATE DATABASE IF NOT EXISTS insurance_claims_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS insurance_claims_migrate CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON `insurance_claims`.* TO 'claims'@'%';
GRANT ALL PRIVILEGES ON `insurance_claims_test`.* TO 'claims'@'%';
GRANT ALL PRIVILEGES ON `insurance_claims_migrate`.* TO 'claims'@'%';
FLUSH PRIVILEGES;
