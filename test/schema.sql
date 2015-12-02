-- MySQL Xenoforo mock up database
CREATE TABLE xf_users (
    user_id INT(10) KEY AUTO_INCREMENT,
    username VARCHAR(10) NOT NULL UNIQUE,
    discord_id VARCHAR(24) NULL
);

-- Token storage
CREATE TABLE discord_tokens (
    user_id INT(10) KEY,
    token CHAR(16) NOT NULL,
    issued TIMESTAMP NOT NULL
);

-- Test web page
CREATE USER 'web'@'localhost' IDENTIFIED BY 'password1';
GRANT SELECT, UPDATE, INSERT, DELETE ON xenotest.* TO 'web'@'localhost';

-- Discord authentication bot
CREATE USER 'auth'@'localhost' IDENTIFIED BY 'password2';
GRANT SELECT (user_id, username, discord_id)  ON xenotest.xf_users
    TO 'auth'@'localhost';
GRANT UPDATE (discord_id) on xenotest.xf_users TO 'auth'@'localhost';
GRANT SELECT, DELETE ON xenotest.discord_tokens
    TO 'auth'@'localhost';