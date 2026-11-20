from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ZyrquenConfig:
    """Hyper-parameters of the ZYRQUEN decoder-only Transformer.

    Defaults target a 1-5M parameter model with a small native vocabulary.
    """

    vocab_size: int = 2048
    max_seq_len: int = 256
    n_layers: int = 4
    n_heads: int = 4
    d_model: int = 256
    d_ff: int = 704
    dropout: float = 0.0
    rope_theta: float = 10000.0
    norm_eps: float = 1e-5
    tie_embeddings: bool = True

    def __post_init__(self) -> None:
        if self.d_model % self.n_heads != 0:
            raise ValueError("d_model must be divisible by n_heads")
        if (self.d_model // self.n_heads) % 2 != 0:
            raise ValueError("head dimension must be even for RoPE")
        for name in ("vocab_size", "max_seq_len", "n_layers", "n_heads", "d_model", "d_ff"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def estimated_num_parameters(self) -> int:
        embedding_count = self.vocab_size * self.d_model
        if not self.tie_embeddings:
            embedding_count *= 2
        block_count = self.n_layers * (
            4 * self.d_model * self.d_model
            + 3 * self.d_model * self.d_ff
            + 2 * self.d_model
        )
        return embedding_count + block_count + self.d_model

    @classmethod
    def from_dict(cls, data: dict) -> "ZyrquenConfig":
        return cls(**data)
