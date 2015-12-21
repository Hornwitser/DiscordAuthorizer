<?php

class DiscordAuth_Model_Token extends XenForo_Model
{
    public function getTokenByUserId($userId)
    {
        $options = XenForo_Application::get('options');

        return $this->_getDb()->fetchRow(
            "SELECT *, NOW() < TIMESTAMPADD(MINUTE, ?, issued) AS valid
             FROM `xf_da_token` WHERE user_id = ?",
            array($options->validPeriod, $userId)
        );
    }
}
