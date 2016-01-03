<?php

class DiscordAuth_ControllerHelper_Account
    extends XFCP_DiscordAuth_ControllerHelper_Account
{
    public function getWrapper(
        $selectedGroup,
        $selectedLink,
        XenForo_ControllerResponse_View $subView
    ) {
        // XenForo_ControllerResponse_View
        $wrapper = parent::getWrapper($selectedGroup, $selectedLink, $subView);

        // Add canLinkDiscord parameter to the account wrapper, which in
        // turn adds it to all account pages, and eventually where it's
        // used in the discordauth_account_wrapper_sidebar template.

        $visitor = XenForo_Visitor::getInstance();
        $canLinkDiscord = $visitor->hasPermission('general', 'linkDiscord');
        $wrapper->params['canLinkDiscord'] = $canLinkDiscord;

        return $wrapper;
    }
}
