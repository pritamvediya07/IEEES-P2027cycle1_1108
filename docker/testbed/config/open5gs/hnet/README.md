# Test-only SUCI home-network keys

`curve25519-1.key` and `secp256r1-2.key` are the UDM home-network private keys used for
SUCI de-concealment in the isolated Open5GS testbed (`../udm.yaml`). They protect nothing:
the testbed uses synthetic subscribers only. Do not reuse them in any other deployment;
generate fresh keys instead:

```bash
openssl genpkey -algorithm X25519 -out curve25519-1.key
openssl ecparam -name prime256v1 -genkey -conv_form compressed -out secp256r1-2.key
```
