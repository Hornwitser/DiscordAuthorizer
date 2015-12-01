<?php

function html($text) {
    return htmlspecialchars($text, ENT_QUOTES|ENT_HTML5, 'UTF-8');
}

$host = $_SERVER['DB_HOST'];
$user = $_SERVER['DB_USER'];
$password = $_SERVER['DB_PASSWORD'];
$schema = $_SERVER['DB_SCHEMA'];
$expire = $_SERVER['EXPIRE'];

$mysqli = new mysqli($host, $user, $password, $schema);
if ($mysqli->connect_errno) {
    header("HTTP/1.0 500 Internal Server Error");
    echo("500 Internal Server Error\n");
    echo("Failed to connect to database: ".$mysqli->connect_error);
    die();
}

if (isset($_GET['create'])) {
    $name = $mysqli->real_escape_string($_GET['username']);
    $res = $mysqli->query(
        "INSERT INTO xf_users SET username = '$name'"
    );

    if (!$res) {
        $error = $mysqli->error;
        $logged_in = false;
    } else {
        $user_id = $mysqli->insert_id;
        $logged_in = true;
        $token = null;
    }

} else if (isset($_GET['username'])) {
    $name = $mysqli->real_escape_string($_GET['username']);
    $res = $mysqli->query(
        "SELECT x.user_id, NOW() < TIMESTAMPADD(MINUTE, $expire, issued), ".
        "token FROM xf_users AS x LEFT JOIN discord_tokens AS d ".
        "ON x.user_id = d.user_id WHERE username = '$name'"
    );

    if (!$res) {
        $error = $mysqli->error;
        $logged_in = false;
    } else if ($res->num_rows === 0) {
        $error = "No user named $_GET[username]";
        $logged_in = false;
    } else {
        list($user_id, $valid, $token) = $res->fetch_row();
        $logged_in = true;
        if ($valid !== '1' && isset($_GET['token'])) {
            /* If you're using any of this code in your website you
               deserve to get pwned.  The following token generation
               code is not safe for use outside of a testing setup
               and should *NOT* be used. */
            $token = str_pad(dechex(rand()), 16, 'x', STR_PAD_LEFT);
            $res = $mysqli->query(
                "INSERT INTO discord_tokens ".
                "SET user_id = $user_id, token = '$token' ON DUPLICATE KEY ".
                "UPDATE token = '$token'"
            );

            if (!$res) {
                $error = $mysqli->error;
            }
        } else if ($valid === '0') {
            $token = null;
        }
    }

} else {
    $logged_id = false;
}

$mysqli->close();

?>
<!DOCTYPE html>
<html>
    <head>
        <meta charset="UTF-8">
        <title>Test ForumBot</title>
    </head>
    <body>
<?php
if (isset($error)) { ?>
        <p>Error: <?=html($error)?>
<?php
}

if (!$logged_in) { ?>
        <form action="forumbot" method="GET">
            Username:
            <input type="text" name="username">
            <input type="submit" value="Log in">
            <input type="submit" name="create" value="Create User">
        </form>
<?php
} else { ?>
        <form action="forumbot" method="GET">
            Logged in as <?=html($_GET['username'])?> <input type="submit" value="Log out">
        </form>
<?php
    if ($token === null) { ?>
        <form action="forumbot" method="GET">
            <input type="hidden" name="username" value="<?=html($_GET['username'])?>">
            <input type="submit" name="token" value="Generate token">
        </form>
<?php
    } else { ?>
        <p>Your token is: <?=$token?>
<?php
    }
} ?>
    </body>
</head>
