<?php

class DiscordAuth_DataWriter_Token extends XenForo_DataWriter
{
    protected function _getFields()
    {
        return array(
            'xf_da_token' => array(
                'user_id' => array(
                    'type' => self::TYPE_UINT,
                    'required' => true,
                ),
                'token' => array(
                    'type' => self::TYPE_STRING,
                    'required' => true,
                ),
            ),
        );
    }

    protected function _getExistingData($data)
    {
        if (!$id = $this->_getExistingPrimaryKey($data, 'user_id')) {
            return false;
        }

        return array(
            'xf_da_token' => $this->_getTokenModel()->getTokenByUserId($id)
        );
    }

    protected function _getUpdateCondition($tableName)
    {
        return 'user_id = '.$this->_db->quote($this->getExisting('user_id'));
    }

    protected function _getTokenModel()
    {
        return $this->getModelFromCache('DiscordAuth_Model_Token');
    }
}
