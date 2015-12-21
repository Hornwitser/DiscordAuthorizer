<?php

class DiscordAuth_Model_Token extends XenForo_Model
{
    public function getValidTokenByUserId($userId)
    {
        $options = XenForo_Application::get('options');

        return $this->_getDb()->fetchRow(
            "SELECT * FROM `xf_da_token` WHERE user_id = ?
             AND NOW() < TIMESTAMPADD(MINUTE, ?, issued)",
            array($userId, $options->validPeriod)
        );
    }

    public function getTokenByUserId($userId)
    {
        return $this->_getDb()->fetchRow(
            "SELECT * FROM `xf_da_token` WHERE user_id = ?",
            array($userId)
        );
    }
}
