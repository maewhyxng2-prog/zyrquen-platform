from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ZyrquenConfig:
    """Hyper-parameters of the ZYRQUEN decoder-only Transformer.

    Defaults describe a deliberately tiny model for pipeline testing only.
    """

    vocab_size: int = 32000
    max_seq_len: int = 512
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

    @classmethod
    def from_dict(cls, data: dict) -> "ZyrquenConfig":
        return cls(**data)
