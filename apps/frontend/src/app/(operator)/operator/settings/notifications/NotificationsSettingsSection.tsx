"use client";

export { NotificationsSettingsSection } from "@/components/settings/NotificationsSettingsSection";
// Also re-export as default to match either import style used by tests.
import { NotificationsSettingsSection as _NotificationsSettingsSection } from "@/components/settings/NotificationsSettingsSection";
const NotificationsSettingsSectionDefault = _NotificationsSettingsSection;
export default NotificationsSettingsSectionDefault;
