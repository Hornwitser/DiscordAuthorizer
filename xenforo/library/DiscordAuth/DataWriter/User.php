<?php

class DiscordAuth_DataWriter_User
    extends XFCP_DiscordAuth_DataWriter_User
{
    protected function _getFields()
    {
        $fields = parent::_getFields();
        $fields['xf_user']['da_discord_id'] = array(
            'type' => self::TYPE_UNKNOWN,
            'required' => false,
        );
        return $fields;
    }

    private function refreshDiscordId($discordId)
    {
        $options = XenForo_Application::get('options');
        if ($options->botSocket === '') {
            return;
        }

        XenForo_Error::debug("Refreshing user $discordId");

        $so = socket_create(AF_UNIX, SOCK_DGRAM, 0);
        if ($so === false) {
            $msg = socket_strerror(socket_last_error());
            $error = "Bot socket create failed: $msg";

            throw new Exception($error);
        }

        $res = socket_connect($so, $options->botSocket);
        if ($res === false) {
            $msg = socket_strerror(socket_last_error());
            $error = "Bot socket connect failed: $msg";

            throw new Exception($error);
        }

        $payload = json_encode(array(
            'action' => 'refresh',
            'user_id' => $discordId,
        ));

        $res = socket_write($so, $payload);
        socket_shutdown($so);
        socket_close($so);

        if ($res === false) {
            $error = "Bot socket send failed";

            throw new Exception($error);

        } else if ($res < strlen($payload)) {
            // This will probably never happen.
            $error = "Bot socket did not send all data";

            throw new Exception($error);
        }
    }

    protected function _postSave()
    {
        parent::_postSave();

        $discordId = $this->getExisting('da_discord_id');
        if ($discordId !== null) {
            XenForo_CodeEvent::addListener(
                'controller_post_dispatch',
                function ($c, $r, $n, $a) use ($discordId) {
                    try {
                        self::refreshDiscordId($discordId);
                    } catch (Exception $e) {
                        XenForo_Error::logException($e, false);
                    }
                }
            );
        }
    }

    protected function _postDelete()
    {
        parent::_postDelete();

        $discordId = $this->getExisting('da_discord_id');
        if ($discordId !== null) {
            XenForo_CodeEvent::addListener(
                'controller_post_dispatch',
                function ($c, $r, $n, $a) use ($discordId) {
                    try {
                        self::refreshDiscordId($discordId);
                    } catch (Exception $e) {
                        XenForo_Error::logException($e, false);
                    }
                }
            );
        }
    }
}
