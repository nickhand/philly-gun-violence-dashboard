import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, verify } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const forge = require('node-forge');
const { privateKey, publicKey } = generateKeyPairSync('rsa', {
  modulusLength: 2048,
  publicExponent: 3,
});
const keys = {
  privateKey: forge.pki.privateKeyFromPem(privateKey.export({ type: 'pkcs1', format: 'pem' })),
  publicKey: forge.pki.publicKeyFromPem(publicKey.export({ type: 'pkcs1', format: 'pem' })),
};
const message = 'DigestAlgorithm security regression';
const digest = createHash('sha256').update(message).digest('latin1');
const asn1 = forge.asn1;
const element = (type, constructed, value) =>
  asn1.create(asn1.Class.UNIVERSAL, type, constructed, value);

function signature({ parameters = true, extraAlgorithm = false, extraDigestInfo = false } = {}) {
  const algorithm = [element(asn1.Type.OID, false, asn1.oidToDer(forge.pki.oids.sha256).getBytes())];
  if (parameters) algorithm.push(element(asn1.Type.NULL, false, ''));
  if (extraAlgorithm) algorithm.push(element(asn1.Type.OCTETSTRING, false, 'unconsumed garbage'));
  const info = [
    element(asn1.Type.SEQUENCE, true, algorithm),
    element(asn1.Type.OCTETSTRING, false, digest),
  ];
  if (extraDigestInfo) info.push(element(asn1.Type.NULL, false, ''));
  return keys.privateKey.sign(asn1.toDer(element(asn1.Type.SEQUENCE, true, info)).getBytes(), 'NONE');
}

test('rejects the nested DigestAlgorithm garbage accepted by published node-forge 1.4.0', () => {
  // CVE-2026-85393 / upstream PR #1152. Default padding validation stays enabled.
  for (const parameters of [true, false]) {
    assert.throws(
      () => keys.publicKey.verify(digest, signature({ parameters, extraAlgorithm: true })),
      /does not contain a valid RSASSA-PKCS1-v1_5 DigestInfo/,
    );
  }
});

test('preserves outer DigestInfo validation and rejects truncated ASN.1', () => {
  assert.throws(
    () => keys.publicKey.verify(digest, signature({ extraDigestInfo: true })),
    /does not contain a valid RSASSA-PKCS1-v1_5 DigestInfo/,
  );
  assert.throws(() => keys.publicKey.verify(digest, keys.privateKey.sign('\x30\xff', 'NONE')));
});

test('accepts valid SHA-256 signatures with optional NULL parameters and interoperates with Node', () => {
  for (const parameters of [true, false]) {
    assert.equal(keys.publicKey.verify(digest, signature({ parameters })), true);
  }
  const md = forge.md.sha256.create();
  md.update(message);
  const signed = keys.privateKey.sign(md);
  assert.equal(verify('sha256', Buffer.from(message), publicKey, Buffer.from(signed, 'latin1')), true);
  assert.equal(keys.publicKey.verify('wrong digest', signed), false);
});

test('listhen resolves the reviewed backport and can generate a signed development certificate', () => {
  const listhenRequire = createRequire(require.resolve('listhen'));
  assert.equal(listhenRequire.resolve('node-forge'), require.resolve('node-forge'));
  assert.equal(require('node-forge/package.json').version, '1.4.1-philly.1');
  const cert = forge.pki.createCertificate();
  cert.publicKey = keys.publicKey;
  cert.serialNumber = '01';
  cert.validity.notBefore = new Date('2026-01-01');
  cert.validity.notAfter = new Date('2027-01-01');
  cert.setSubject([{ name: 'commonName', value: 'localhost' }]);
  cert.setIssuer(cert.subject.attributes);
  cert.sign(keys.privateKey, forge.md.sha256.create());
  assert.equal(cert.verify(cert), true);
  assert.match(forge.pki.certificateToPem(cert), /BEGIN CERTIFICATE/);
});

test('the exact audited local archive is unchanged and no registry forge copy remains in the lock', () => {
  const archive = readFileSync(new URL('../vendor/node-forge-1.4.1-philly.1.tgz', import.meta.url));
  assert.equal(
    createHash('sha256').update(archive).digest('hex'),
    'ea17a195ef66d4b10c9fb3093c26516d40be0da7d14b53ca6a842bc31e2b1ccc',
  );
  const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));
  const copies = Object.entries(lock.packages).filter(([path]) => path.endsWith('/node-forge'));
  assert.equal(copies.length, 1);
  assert.equal(copies[0][1].resolved, 'file:vendor/node-forge-1.4.1-philly.1.tgz');
});
