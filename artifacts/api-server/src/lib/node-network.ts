import dns from "node:dns";

const GOOGLE_OAUTH_HOSTS = new Set([
  "accounts.google.com",
  "oauth2.googleapis.com",
]);

type LookupCallback = (
  err: NodeJS.ErrnoException | null,
  address:
    | string
    | Array<{
        address: string;
        family: 4;
      }>,
  family?: number
) => void;

/**
 * Local Linux networks can expose broken IPv6/DNS behavior to Node while curl
 * still works. Better Auth exchanges Google OAuth codes with Node fetch, so a
 * timeout here breaks mobile sign-in after Google redirects back.
 *
 * This shim is opt-in and local-development only. It forces the Google OAuth
 * hosts through IPv4 resolution while leaving every other hostname untouched.
 */
export function installGoogleOAuthIpv4Lookup(): void {
  if (process.env["DAWA_FORCE_GOOGLE_OAUTH_IPV4"] !== "true") return;

  const originalLookup = dns.lookup.bind(dns);

  dns.lookup = ((hostname: string, options: unknown, callback?: unknown) => {
    let opts = options as dns.LookupAllOptions | dns.LookupOneOptions | undefined;
    let cb = callback as LookupCallback | undefined;

    if (typeof options === "function") {
      cb = options as LookupCallback;
      opts = undefined;
    }

    if (!cb || !GOOGLE_OAUTH_HOSTS.has(hostname)) {
      return originalLookup(hostname, opts as dns.LookupAllOptions, cb as never);
    }

    return dns.resolve4(hostname, (err, addresses) => {
      if (!err && addresses?.[0]) {
        if ((opts as dns.LookupAllOptions | undefined)?.all) {
          return cb(
            null,
            addresses.map((address) => ({ address, family: 4 }))
          );
        }

        return cb(null, addresses[0], 4);
      }

      return originalLookup(hostname, opts as dns.LookupAllOptions, cb as never);
    });
  }) as typeof dns.lookup;
}
