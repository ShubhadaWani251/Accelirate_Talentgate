"""Generates the certificate/private-key pair for certificate-based Microsoft Graph
authentication (see api/services/graph_email.py's module docstring for why this is preferred
over the GRAPH_CLIENT_SECRET this app currently uses).

This command only creates the files and prints what to do with them - it cannot register
anything with Azure AD itself (that needs an Entra ID admin, which this app has no access to,
by design: the whole point of moving off a shared secret is fewer things able to authenticate as
the app). Three manual steps remain after running it:

1. In the Azure Portal, open the app registration used for GRAPH_CLIENT_ID -> Certificates &
   secrets -> Certificates tab -> Upload certificate, and upload the .cer file this command
   writes (the PUBLIC certificate only - never upload the .pem private key anywhere).
2. Azure will display a thumbprint for the uploaded certificate. Copy it exactly - it should
   match the one this command prints, but Azure's own display is the authoritative source.
3. Set two environment variables for the app: GRAPH_CERT_PATH to the .pem file's path on the
   server, and GRAPH_CERT_THUMBPRINT to the thumbprint from step 2. Leave GRAPH_CLIENT_SECRET in
   place as a fallback, or remove it once cert auth is confirmed working - graph_email.py prefers
   the certificate whenever both are configured.

The generated certificate is self-signed and valid for 2 years from generation - Azure AD does
not require a CA-issued certificate for app authentication, since it is Azure that verifies the
signature against the public certificate it was given directly, not against a certificate
authority's chain of trust.

    python manage.py generate_graph_cert
    python manage.py generate_graph_cert --out-dir Backend/certs --years 2
"""

import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generates a self-signed certificate/private-key pair for Graph API cert-based auth.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--out-dir', default='certs',
            help='Directory to write the key pair into (default: certs, relative to Backend/). '
                 'Already gitignored - never commit these files.',
        )
        parser.add_argument(
            '--years', type=int, default=2,
            help='Certificate validity in years (default: 2). Longer means fewer rotations; '
                 'shorter limits how long a compromised key stays useful.',
        )
        parser.add_argument(
            '--common-name', default='talentgate-graph-mail',
            help='Certificate subject/issuer common name - cosmetic only, Azure AD does not '
                 'check it (default: talentgate-graph-mail).',
        )

    def handle(self, *args, **options):
        out_dir = Path(options['out_dir'])
        out_dir.mkdir(parents=True, exist_ok=True)
        key_path = out_dir / 'graph-mail-key.pem'
        cert_pem_path = out_dir / 'graph-mail-cert.pem'
        cert_cer_path = out_dir / 'graph-mail-cert.cer'

        for existing in (key_path, cert_pem_path, cert_cer_path):
            if existing.exists():
                raise SystemExit(
                    f'{existing} already exists - remove it first if you really want to '
                    f'regenerate (that invalidates the certificate already uploaded to Azure, '
                    f'if any).'
                )

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, options['common_name']),
        ])
        now = datetime.datetime.now(datetime.timezone.utc)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))  # small clock-skew allowance
            .not_valid_after(now + datetime.timedelta(days=365 * options['years']))
            .sign(private_key, hashes.SHA256())
        )

        key_path.write_bytes(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        cert_pem_bytes = certificate.public_bytes(serialization.Encoding.PEM)
        cert_pem_path.write_bytes(cert_pem_bytes)
        # .cer (DER) is what the Azure Portal's "Upload certificate" dialog expects.
        cert_cer_path.write_bytes(certificate.public_bytes(serialization.Encoding.DER))

        # GRAPH_CERT_PATH needs BOTH the private key and the certificate in one file - jwt.encode
        # in graph_email.py loads this as the signing key.
        combined_path = out_dir / 'graph-mail-key-and-cert.pem'
        combined_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ) + cert_pem_bytes
        )

        thumbprint = certificate.fingerprint(hashes.SHA1()).hex()

        self.stdout.write(self.style.SUCCESS(f'Generated a {options["years"]}-year certificate.'))
        self.stdout.write('')
        self.stdout.write(f'  Private key + cert (for GRAPH_CERT_PATH): {combined_path}')
        self.stdout.write(f'  Public certificate only (upload to Azure): {cert_cer_path}')
        self.stdout.write(f'  Thumbprint (for GRAPH_CERT_THUMBPRINT):    {thumbprint}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(
            f'Next: upload {cert_cer_path.name} to the app registration in the Azure Portal '
            f'(Certificates & secrets -> Certificates -> Upload certificate), confirm the '
            f'thumbprint Azure shows matches the one above, then set:\n'
            f'  GRAPH_CERT_PATH={combined_path}\n'
            f'  GRAPH_CERT_THUMBPRINT={thumbprint}\n'
            f'Keep {combined_path.name} out of source control - it holds the private key '
            f'(already covered by .gitignore\'s Backend/certs/ entry if written under the '
            f'default --out-dir).'
        ))
