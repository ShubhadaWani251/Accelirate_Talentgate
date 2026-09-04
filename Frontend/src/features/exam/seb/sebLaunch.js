import { baseURL } from '../../../api/examAxiosClient';

// Two pure URL builders - no fetch, no side effects. configUrl is a plain download link;
// sebLaunchUrl is the same address with its scheme swapped for SEB's own custom protocol, which
// is what makes an <a href> to it hand the request to an installed SEB instead of the browser
// (seb:// for a plain-HTTP config URL, sebs:// once the deployment is HTTPS - SEB apparently
// treats sebs:// as "must fetch the config over HTTPS", so deriving from the URL's own scheme
// rather than hardcoding one keeps local dev and a real deployment both correct with no extra
// env var).
//
// TODO confirm against SEB's current developer documentation: this assumes a straight scheme
// swap on the config URL is the whole of it. Not verified against a real SEB client.
export function configUrl(token) {
  return `${baseURL}/exam/token/${token}/seb-config/`;
}

export function sebLaunchUrl(token) {
  const url = configUrl(token);
  return url.startsWith('https:') ? url.replace('https:', 'sebs:') : url.replace('http:', 'seb:');
}
