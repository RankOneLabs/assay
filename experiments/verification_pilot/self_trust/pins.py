"""Literal st-v2 prompt identity captured from the rendered prompt surface."""

SYSTEM_PROMPT_SHA256: dict[tuple[str, str], str] = {
    (
        "forge-move",
        "matched",
    ): "sha256:28443b6ab0f7cd66ecd9e830f75214c6e3494e0bc8fe41f1e7251308b51cc039",
    (
        "forge-move",
        "own_work",
    ): "sha256:6ba628e8418a4cdffc17ad9685d9c3dff241c2bfa2ec95beb33f4498a9981a61",
    (
        "forge-move",
        "verifier",
    ): "sha256:8bf3f9c002f9d8cce09d176a5984ed33c86f29a21da5ed3ccb30c28c2d59f73b",
    (
        "forge-rewrite",
        "matched",
    ): "sha256:401e507ff5f59930eaf9df869ff0d591017c9e4f30bdf67218628c4506bbdff1",
    (
        "forge-rewrite",
        "own_work",
    ): "sha256:3a4fcb267fbb1b6dfb9a97285d43d3cb9634a36f5e352d42a1074eaa1955b6d0",
    (
        "forge-rewrite",
        "verifier",
    ): "sha256:d4dabf30ef84f80d39c1202f5072d3d84bf00206f15fd7e79719bc392ca7f013",
    (
        "refactor",
        "matched",
    ): "sha256:3577fdf4a1222b5c829038f8fb4201927fa5bfb0f04d3ba8ebbc87fbe822248b",
    (
        "refactor",
        "two_teammates",
    ): "sha256:8dc21d8b5aabe1a61dc0eb87b94caa6e685eaaa97c9e2617bf0092b75077fbe7",
    (
        "refactor-long",
        "matched",
    ): "sha256:3577fdf4a1222b5c829038f8fb4201927fa5bfb0f04d3ba8ebbc87fbe822248b",
    (
        "refactor-long",
        "two_teammates",
    ): "sha256:8dc21d8b5aabe1a61dc0eb87b94caa6e685eaaa97c9e2617bf0092b75077fbe7",
    (
        "resume146",
        "matched",
    ): "sha256:ff5b2f1d98f7a50882e8a3fbd0b73e7d41bee059f2e01e981b0aaec701344831",
    (
        "resume146",
        "own_work",
    ): "sha256:8b34c238106aa543dd419c7cafb8b9664cf094ccd6ae64cab87ba9b5b2d57927",
    (
        "resume146",
        "verifier",
    ): "sha256:b3bd39d777a602b8e89e28dcad3f68c80eb49afefe00a46f748b3dff3f2156b3",
    (
        "rewrite",
        "matched",
    ): "sha256:f16496609421cfdacf609abe7188e2d3ffec824fea840c61807b32bd05043ba0",
    (
        "rewrite",
        "two_teammates",
    ): "sha256:0c8f0660f43b56f2d41c60017d5404d333c76425ffe053ea9cea8541387d634e",
    (
        "rewrite0",
        "matched",
    ): "sha256:cb68ab81c85093c0d1c274435301d96c105c5251d9224ba4e5a80ec867b98249",
    (
        "rewrite0",
        "own_work",
    ): "sha256:7ba04923599180cc0ec4aef64032c862a6e9339fce6dd63b4fb57d42c461eff8",
    (
        "rewrite0",
        "verifier",
    ): "sha256:f9643ff2e03b2f9ac9ad57352a3d3091f65d55f519f561bb0e1282e96760a328",
    (
        "rewrite0-read",
        "matched",
    ): "sha256:cb68ab81c85093c0d1c274435301d96c105c5251d9224ba4e5a80ec867b98249",
    (
        "rewrite0-read",
        "own_work",
    ): "sha256:7ba04923599180cc0ec4aef64032c862a6e9339fce6dd63b4fb57d42c461eff8",
    (
        "rewrite0-read",
        "verifier",
    ): "sha256:f9643ff2e03b2f9ac9ad57352a3d3091f65d55f519f561bb0e1282e96760a328",
    (
        "rewrite1",
        "matched",
    ): "sha256:25098b3b7aa77ce3a9a8138a274b80befc295d04777830b30341c9c3ba4aa5b8",
    (
        "rewrite1",
        "own_work",
    ): "sha256:f4d3032898035c94f5f63724a24c420262ebbde9f7d92808d1f7aa052f7e66ca",
    (
        "rewrite1",
        "verifier",
    ): "sha256:daada507df6a5cae74eed63c708d0b256a725c7dbbe587a480fe436c056c50b9",
    (
        "rewrite2",
        "matched",
    ): "sha256:6f31783a8fad43de0ac7aad3d6ddc8f097f95f1e2381b38526e347eeb20dfbd2",
    (
        "rewrite2",
        "one_teammate",
    ): "sha256:9ad36fbc9937cac25280aa5c1252475f3406841497d6a7b9105c9efd8820fc69",
    (
        "rewrite2",
        "verifier",
    ): "sha256:07ce1f94b12590d5c8f09d16c86069dbbe354200d780a7f865a22b11fc2d10bb",
}

RENAME_SYSTEM_PROMPT_SHA256 = (
    "sha256:a6d260a73a2a3474aac9579d1a61c11c6fd4b0f64cbea6f822afffab2cb71b7b"
)
TURN_PROMPTS_SHA256 = "sha256:2756db22bf70f7d851e9cc1da10d8ff7e58c6b88efb446d9a860a9c1bd3fdfc6"
