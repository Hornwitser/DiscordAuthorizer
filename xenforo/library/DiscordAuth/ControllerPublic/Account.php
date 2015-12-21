<?php

class DiscordAuth_ControllerPublic_Account
    extends XFCP_DiscordAuth_ControllerPublic_Account
{
    protected function _getTokenModel()
    {
        return $this->getModelFromCache('DiscordAuth_Model_Token');
    }

    public function actionDiscord()
    {
        $tokenModel = $this->_getTokenModel();
        $visitor = XenForo_Visitor::getInstance();
        $token = $tokenModel->getValidTokenByUserId($visitor['user_id']);

        $viewParams = array(
            'token' => $token,
        );

        return $this->_getWrapper(
            'account', 'discord',
            $this->responseView(
                'DiscordAuth_ViewPublic_Account_Discord',
                'discordauth_account_discord',
                $viewParams
            )
        );
    }

    public function actionDiscordLink()
    {
        $this->_assertPostOnly();

        $tokenModel = $this->_getTokenmodel();
        $visitor = XenForo_Visitor::getInstance();

        $generate = $this->_input->filterSingle(
            'create',
            XenForo_Input::STRING,
            array('default' => '')
        );

        if (strlen($generate)) {
            /* If you're using any of this code in your website you
               deserve to get pwned.  The following token generation
               code is not safe for use outside of a testing setup
               and should *NOT* be used. */
            $token = str_pad(dechex(rand()), 16, 'x', STR_PAD_LEFT);
            // TODO: proper token generation

            $dw = XenForo_DataWriter::create('DiscordAuth_DataWriter_Token');
            $existing = $tokenModel->getTokenByUserId($visitor['user_id']);
            if ($existing !== false) {
                $dw->setExistingData($existing, true);
            }

            $dw->set('user_id', $visitor['user_id']);
            $dw->set('token', $token);
            $dw->save();
        }

        $unlink = $this->_input->filterSingle(
            'unlink',
            XenForo_Input::STRING,
            array('default' => '')
        );

        if (strlen($unlink)) {
            $dw = XenForo_DataWriter::create('XenForo_DataWriter_User');
            $dw->setExistingData($visitor['user_id']);
            $dw->set('da_discord_id', null);
            $dw->save();
        }

        return $this->responseRedirect(
            XenForo_ControllerResponse_Redirect::SUCCESS,
            $this->getDynamicRedirect(
                XenForo_Link::buildPublicLink('account/discord')
            )
        );
    }
}
