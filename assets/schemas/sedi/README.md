# SEDI schema snapshots

These 11 public schema definitions ship with Locksmith as Qt resources under
`:/assets/schemas/sedi/`. They are draft definitions, version 0.1.0.

Source: [Keripy tests/sedi/test_sedi.py at d0d5af47](https://github.com/WebOfTrust/keripy/blob/d0d5af47f7967192ca18889e614b9b8f055f5f7d/tests/sedi/test_sedi.py).
This is Locksmith's current locked Keripy revision. The JSON preserves each
source definition and its field order. Filenames describe the credential type.
The embedded `$id` identifies the exact schema.

| Schema | File | SAID |
| --- | --- | --- |
| SEDI AID Replace Schema | [aid-replacement.json](aid-replacement.json) | `EPVlX-S-eWERGiXJmb7FcW75I4J08ptQ-jGglq4VRwou` |
| SEDI Organizational Unit Schema | [organizational-unit.json](organizational-unit.json) | `EBbOpBe0lP_epHhakeiXdOmeal3leDfLRf0PAItsanoQ` |
| SEDI Issuing Agent Schema | [issuing-agent.json](issuing-agent.json) | `EGx4BLclkjhaK1501guyBifxuTTJLwuK61InBTdkKF7v` |
| SEDI IAR Schema | [iar.json](iar.json) | `EFAB6k77bXHs6bg9PORW7UYF79GD_OuEcEjmBpwhcfRN` |
| SEDI Core Schema | [core-identity.json](core-identity.json) | `EN0JtdzBmFuTUzyJG9CXZhtdu-bW0V6L95bsVBzi-cY-` |
| SEDI Guardianship Schema | [guardianship.json](guardianship.json) | `EDJzXg34opr6-odFix6lpiccfHF7ksITHuIES_MQRH4b` |
| SEDI Residence Schema | [residence.json](residence.json) | `EH5hn7CbtDFxhS3IKioC8P-e4YyZoxqzhRpr4X_e32BD` |
| SEDI Age Schema | [age.json](age.json) | `EPqXrwPT6b0_KghrrMuIdmuD68Aytv1XK6jU86EumgJV` |
| SEDI High Resolution Facial Image Proof Schema | [facial-image-proof.json](facial-image-proof.json) | `EKuGAkHNpj5ujsEWQuZFe8bbuSrIOwojUNjgirDtWIAb` |
| SEDI Social Authorization Schema | [social-authorization.json](social-authorization.json) | `EB8MUTKRg8284YPduyhDgUVvNM192-247KcRaXhIxoni` |
| SEDI Bespoke Presentation Schema | [bespoke-presentation.json](bespoke-presentation.json) | `EGcqmkrnaQz8F1PEekLOaySiW-uDaJ0SfoqtSuqCvEif` |

The [SEDI guide at eda11589](https://github.com/keri-foundation/sedi/blob/eda11589973ff27565381a3e07018858d4db50bd/sedi_guide.md)
contains all 11 definitions.

In Load Credential Schema, select **Built-in**, choose a schema, then select
**Load Schema**. The dialog uses the existing schema loader. It verifies the
embedded SAID and saves the schema in the current vault. Repeated loads use the
same cache entry. Issuer selection remains optional; loading creates no registry.
