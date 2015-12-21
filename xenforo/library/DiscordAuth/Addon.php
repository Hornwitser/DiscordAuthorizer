<?php

class DiscordAuth_Addon
{
    public static function templateHookListener(
        $hookName,
        &$contents,
        array $hookParams,
        XenForo_Template_Abstract $template
    ) {
        switch ($hookName) {
            case 'account_wrapper_sidebar_settings':
                $contents .= $template->create(
                    'discordauth_account_wrapper_sidebar',
                    $template->getParams()
                )->render();
                break;

            case 'member_view_tabs_content':
                $contents .= $template->create(
                    'discordauth_profile_tab_content',
                    $template->getParams()
                )->render();
                break;

            case 'navigation_visitor_tab_links1':
                $contents .= $template->create(
                    'discordauth_navigation_tab_link',
                    $template->getParams()
                )->render();
                break;
        }
    }

    public static function loadClassListener($class, &$extend)
    {
        switch ($class) {
            case 'XenForo_DataWriter_User':
                $extend[] = 'DiscordAuth_DataWriter_User';
                break;

            case 'XenForo_ControllerPublic_Account':
                $extend[] = 'DiscordAuth_ControllerPublic_Account';
                break;
        }
    }

    protected static $table_create = "
        CREATE TABLE `xf_da_token` (
            `user_id` INT UNSIGNED NOT NULL,
            `token` CHAR(16) NOT NULL,
            `issued` TIMESTAMP NOT NULL,
            PRIMARY KEY (`user_id`),
            KEY `token` (`token`)
        ) ENGINE = InnoDB CHARACTER SET utf8 COLLATE utf8_general_ci
    ";

    protected static $table_drop = "
        DROP TABLE IF EXISTS `xf_da_token`
    ";

    protected static $column_show = "
        SHOW COLUMNS FROM `xf_user` LIKE 'da_discord_id'
    ";

    protected static $column_create = "
        ALTER TABLE `xf_user`
            ADD COLUMN `da_discord_id` VARCHAR(24) NULL UNIQUE
    ";

    protected static $column_drop = "
        ALTER TABLE `xf_user`
            DROP COLUMN `da_discord_id`
    ";

    public static function install($addOn)
    {
        $version = is_array($addOn) ? $addOn['version_id'] : 0;

        if ($version < 1) { // AddOn is not installed
            $db = XenForo_Application::get('db');
            $db->query(self::$table_create);
            $db->query(self::$column_create);
        }
    }

    public static function uninstall()
    {
        // The uninstall actions fail gracefully if the modifications
        // are not present in the database.

        $db = XenForo_Application::get('db');
        $db->query(self::$table_drop);

        $column = $db->fetchOne(self::$column_show);
        if ($column !== false) {
            $db->query(self::$column_drop);
        }
    }
}
