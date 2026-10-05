/** First letters of a user's name, for an avatar. Empty string when there is no user.
 *
 * Shared rather than defined twice: the sidebar's account card and the header's account strip
 * both show the same avatar for the same person, and two copies of this could drift into
 * disagreeing about someone's initials on one screen.
 */
export function initials(user) {
  if (!user) return '';
  return `${user.first_name?.[0] || ''}${user.last_name?.[0] || ''}`.toUpperCase();
}
