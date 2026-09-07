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

// A zipped alternative to configUrl - some candidate machines (Chrome Enterprise policy /
// corporate DLP) hard-block a bare .seb download outright with no override offered, reported
// live and reproduced with an identical block on .webm too (see services/seb.build_config_zip
// on the backend). .zip is about the most universally-unblocked format there is, so this is a
// genuine fallback for exactly that case - the candidate just has to extract it first.
export function configZipUrl(token) {
  return `${baseURL}/exam/token/${token}/seb-config.zip/`;
}
