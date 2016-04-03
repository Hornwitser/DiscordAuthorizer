<?php

function html($text) {
    return htmlspecialchars($text, ENT_QUOTES|ENT_HTML5, 'UTF-8');
}

$host = $_SERVER['DB_HOST'];
$user = $_SERVER['DB_USER'];
$password = $_SERVER['DB_PASSWORD'];
$schema = $_SERVER['DB_SCHEMA'];
$expire = $_SERVER['EXPIRE'];
$socket = $_SERVER['SOCKET'];

function refresh_user($discord_id) {
    global $socket, $error;

    $so = socket_create(AF_UNIX, SOCK_DGRAM, 0);
    if ($so === false) {
        $msg = socket_strerror(socket_last_error());
        $error = "Socket failed: $msg";

    } else {
        $res = socket_connect($so, $socket);
        if ($res === false) {
            $msg = socket_strerror(socket_last_error());
            $error = "Connect failed: $msg";

        } else {
            $payload = json_encode(array(
                'action' => 'refresh',
                'discord_id' => $discord_id,
            ));

            $res = socket_write($so, $payload);
            if ($res === false) {
                $error = "Socket send failed";

            } else if ($res < strlen($payload)) {
                $error = "Socket did not send all data";
            }

            socket_shutdown($so);
            socket_close($so);
        }
    }
}

$mysqli = new mysqli($host, $user, $password, $schema);
if ($mysqli->connect_errno) {
    header("HTTP/1.0 500 Internal Server Error");
    echo("500 Internal Server Error\n");
    echo("Failed to connect to database: ".$mysqli->connect_error);
    die();
}

if (isset($_GET['create']) && isset($_GET['username'])
        && isset($_GET['password'])) {
    $name = $mysqli->real_escape_string($_GET['username']);

    if ($_GET['password'] !== '') {
        $pw = "'".hash('sha256', $_GET['password'])."'";
    } else {
        $pw = 'NULL';
    }

    $res = $mysqli->query(
        "INSERT INTO xf_user SET username = '$name', user_group_id = 1, ".
        "secondary_group_ids = '', is_banned = 0, web_pw = $pw"
    );

    if (!$res) {
        $error = $mysqli->error;
        $logged_in = false;
    } else {
        $user_id = $mysqli->insert_id;
        $logged_in = true;
        $token = null;
        $discord_id = null;
        $group_id = 1;
        $secondary_ids = "";
        $is_banned = 0;
    }

} else if (isset($_GET['username']) && isset($_GET['password'])) {
    $name = $mysqli->real_escape_string($_GET['username']);
    $res = $mysqli->query(
        "SELECT x.user_id, NOW() < TIMESTAMPADD(MINUTE, $expire, issued), ".
        "token, da_discord_id, user_group_id, secondary_group_ids, ".
        "is_banned, web_pw FROM xf_user AS x LEFT JOIN xf_da_token AS d ".
        "ON x.user_id = d.user_id WHERE username = '$name'"
    );

    if (!$res) {
        $error = $mysqli->error;
        $logged_in = false;
    } else if ($res->num_rows === 0) {
        $error = "No user named $_GET[username]";
        $logged_in = false;
    } else {
        list($user_id, $valid, $token, $discord_id, $group_id,
             $secondary_ids, $is_banned, $web_pw) = $res->fetch_row();

        if ($web_pw !== null
                && hash('sha256', $_GET['password']) !== $web_pw) {
            $logged_in = false;
            $error = "Incorrect password";
        } else {
            $logged_in = true;

            if (isset($_GET['revoke'])) {
                $res = $mysqli->query(
                    "UPDATE xf_user SET da_discord_id = NULL ".
                    "WHERE user_id = $user_id"
                );

                if (!$res) {
                    $error = $mysqli->error;

                } else {
                    refresh_user($discord_id);
                    $discord_id = null;
                }


            } else if ($valid !== '1' && isset($_GET['token'])) {
                /* If you're using any of this code in your website you
                   deserve to get pwned.  The following token generation
                   code is not safe for use outside of a testing setup
                   and should *NOT* be used. */
                $token = str_pad(dechex(rand()), 16, 'x', STR_PAD_LEFT);
                $res = $mysqli->query(
                    "INSERT INTO xf_da_token ".
                    "SET user_id = $user_id, token = '$token' ".
                    "ON DUPLICATE KEY UPDATE token = '$token'"
                );

                if (!$res) {
                    $error = $mysqli->error;
                }
            } else if ($valid === '0') {
                $token = null;
            }

            if (isset($_GET['update'])) {
                $gid = (int)$_GET['group_id'];
                $sids = $mysqli->real_escape_string($_GET['secondary_ids']);
                $banned = (int)isset($_GET['banned']);
                $res = $mysqli->query(
                    "UPDATE xf_user SET user_group_id = $gid, ".
                    "secondary_group_ids = '$sids', is_banned = $banned ".
                    "WHERE user_id = $user_id"
                );

                if (!$res) {
                    $error = $mysqli->error;
                } else {
                    refresh_user($discord_id);
                    $group_id = $gid;
                    $secondary_ids = $_GET['secondary_ids'];
                    $is_banned = $banned;
                }
            }
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
        <h4>Forum test</h4>
        <div style="border: 3px solid red; padding: 0 5px; width: 30%; margin: 1em;">
            <b>Warning:</b> Password is sent <i>and logged</i> in plain text!
            The password can only be set when creating the account, and using
            it is entirely optional.
        </div>
        <form action="forumbot" method="GET">
            Username:
            <input type="text" name="username">
            Password:
            <input type="text" name="password">
            <input type="submit" value="Log in">
            <input type="submit" name="create" value="Create User">
        </form>
<?php
} else { ?>
        <h4>User panel</h4>
        <form action="forumbot" method="GET">
            Logged in as <?=html($_GET['username'])?> <input type="submit" value="Log out">
        </form>
<?php
    if ($token === null) { ?>
        <form action="forumbot" method="GET">
            <input type="hidden" name="username" value="<?=html($_GET['username'])?>">
            <input type="hidden" name="password" value="<?=html($_GET['password'])?>">
            <input type="submit" name="token" value="Generate token">
<?php
        if ($discord_id !== null) { ?>
            <input type="submit" name="revoke" value="Revoke Discord Account">
<?php
        } ?>
        </form>
<?php
    } else { ?>
        <p>Your token is: <?=$token?>
<?php
        if ($discord_id !== null) { ?>
        <form action="forumbot" method="GET">
            <input type="hidden" name="username" value="<?=html($_GET['username'])?>">
            <input type="hidden" name="password" value="<?=html($_GET['password'])?>">
            <input type="submit" name="revoke" value="Revoke Discord Account">
        </form>
<?php
        }
    } ?>
        <h4>Admin panel</h4>
        <form action="forumbot" method="GET">
            <input type="hidden" name="username" value="<?=html($_GET['username'])?>">
            <input type="hidden" name="password" value="<?=html($_GET['password'])?>">
            Group id <input type="text" name="group_id" value="<?=$group_id?>">
            Secondary ids <input type="text" name="secondary_ids" value="<?=html($secondary_ids)?>">
            Banned: <input type="checkbox" name="banned"<?=$is_banned ? ' checked' : ''?>>
            <input type="submit" name="update" value="Update Account">
        </form>
<?php
} ?>
    </body>
</head>
