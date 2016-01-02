<?php

class DiscordAuth_ControllerPublic_Account
    extends XFCP_DiscordAuth_ControllerPublic_Account
{
    protected function _getTokenModel()
    {
        return $this->getModelFromCache('DiscordAuth_Model_Token');
    }

    protected static function generateToken()
    {
        $buf = mcrypt_create_iv(12, MCRYPT_DEV_URANDOM);
        if ($buf === false) {
            throw new Exception("Unable to securly generate token");
        }

        return base64_encode($buf);
    }

    public function actionDiscord()
    {
        $tokenModel = $this->_getTokenModel();
        $visitor = XenForo_Visitor::getInstance();
        $token = $tokenModel->getTokenByUserId($visitor['user_id']);

        if ($token !== false && !$token['valid']) {
            $token = false;
        }

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
            $dw = XenForo_DataWriter::create('DiscordAuth_DataWriter_Token');
            $existing = $tokenModel->getTokenByUserId($visitor['user_id']);

            if ($existing === false || !$existing['valid']) {
                if ($existing !== false) {
                    $dw->setExistingData($existing, true);
                }

                try {
                    $dw->set('user_id', $visitor['user_id']);
                    $dw->set('token', self::generateToken());
                    $dw->save();

                // self::generateToken may throw Exception
                } catch (Exception $e) {
                    XenForo_Error::logException($e, false);
                }
            }
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
