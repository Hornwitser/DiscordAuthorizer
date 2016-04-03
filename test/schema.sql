-- MySQL Xenoforo mock up database
CREATE DATABASE xenauth;

CREATE TABLE xenauth.xf_user (
    user_id INT(10) KEY AUTO_INCREMENT,
    username VARCHAR(35) NOT NULL UNIQUE,
    da_discord_id VARCHAR(24) NULL UNIQUE,
    user_group_id INT(10) NOT NULL,
    secondary_group_ids VARBINARY(255) NOT NULL,
    is_banned TINYINT(3) NOT NULL DEFAULT 0,
    web_pw VARCHAR(64) NULL
);

-- Token storage
CREATE TABLE xenauth.xf_da_token (
    user_id INT(10) KEY,
    token CHAR(16) NOT NULL,
    issued TIMESTAMP NOT NULL
);

-- Test web page
CREATE USER 'xenauth'@'localhost' IDENTIFIED BY 'password1';
GRANT SELECT, UPDATE, INSERT, DELETE ON xenauth.* TO 'xenauth'@'localhost';

-- Discord authentication bot
CREATE USER 'authbot'@'localhost' IDENTIFIED BY 'password2';
GRANT SELECT (user_id, username, da_discord_id, user_group_id,
              secondary_group_ids, is_banned)
    ON xenauth.xf_user TO 'authbot'@'localhost';
GRANT UPDATE (da_discord_id) on xenauth.xf_user TO 'authbot'@'localhost';
GRANT SELECT, DELETE ON xenauth.xf_da_token
    TO 'authbot'@'localhost';
