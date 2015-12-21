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
        XenForo_Error::debug("Refreshing user $discordId");
        $options = XenForo_Application::get('options');
        if ($options->botSocket === '') {
            XenForo_Error::debug("Bot socket not configured");
            return;
        }

        $so = socket_create(AF_UNIX, SOCK_DGRAM, 0);
        if ($so === false) {
            $msg = socket_strerror(socket_last_error());
            $error = "Bot socket create failed: $msg";
            XenForo_Error::logException(new Exception($error));
            // Note: XenForo_Error::logError(...) is broken
            return;
        }

        $res = socket_connect($so, $options->botSocket);
        if ($res === false) {
            $msg = socket_strerror(socket_last_error());
            $error = "Bot socket connect failed: $msg";
            XenForo_Error::logException(new Exception($error));
            // Note: XenForo_Error::logError(...) is broken
            return;
        }

        $payload = json_encode(array(
            'action' => 'refresh',
            'user_id' => $discordId,
        ));

        $res = socket_write($so, $payload);
        if ($res === false) {
            $error = "Bot socket send failed";
            XenForo_Error::logException(new Exception($error));
            // Note: XenForo_Error::logError(...) is broken

        } else if ($res < strlen($payload)) {
            $error = "Bot socket did not send all data";
            XenForo_Error::logException(new Exception($error));
            // Note: XenForo_Error::logError(...) is broken
        }

        socket_shutdown($so);
        socket_close($so);

        // Todo: Catch eceptions and log them.
    }

    public function _postSave()
    {
        parent::_postSave();

        $discordId = $this->getExisting('da_discord_id');
        if ($discordId !== null) {
            XenForo_CodeEvent::addListener(
                'controller_post_dispatch',
                function ($c, $r, $n, $a) use ($discordId) {
                    self::refreshDiscordId($discordId);
                }
            );
        }
    }

    public function _postDelete()
    {
        parent::_postDelete();

        $discordId = $this->getExisting('da_discord_id');
        if ($result && $discordId !== null) {
            XenForo_CodeEvent::addListener(
                'controller_post_dispatch',
                function ($c, $r, $n, $a) use ($discordId) {
                    self::refreshDiscordId($discordId);
                }
            );
        }
    }
}
