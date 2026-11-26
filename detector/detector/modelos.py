"""Os cinco baselines atrás de uma interface única (padrão Strategy).

Todo detector:
- `ajustar(X, X_val)`: aprende só com dados de treino (sem falha injetada);
- `pontuar(X)`: devolve o score bruto, MAIOR = MAIS ANÔMALO;
- `para_onnx()`: devolve um modelo ONNX com entrada `x` (float32) e uma saída `score` [N], igual a `pontuar`.

Entrada tabular: `x` [N, d] com os atributos de `atributos.nomes_tab`.
Entrada em sequência (LSTM-AE): `x` [N, L, d] com os últimos L minutos de `atributos.nomes_seq`.

Hiperparâmetros fixados ANTES de olhar a calibração e o teste (registrados no DIARIO.md, seção B).
Nenhum é ajustado no teste.
"""
from __future__ import annotations

import time

import numpy as np

OPSET = 17
OPSET_ML = 3


def _sufixar_neg(modelo_onnx, saida: str, d: int | None = None):
    """Acrescenta ao grafo um nó Neg (e Reshape para [N]) sobre `saida`; a única saída passa a ser `score`."""
    import onnx
    from onnx import TensorProto, helper
    g = modelo_onnx.graph
    forma = helper.make_tensor("forma_n", TensorProto.INT64, [1], [-1])
    g.initializer.append(forma)
    g.node.append(helper.make_node("Reshape", [saida, "forma_n"], ["score_n"]))
    g.node.append(helper.make_node("Neg", ["score_n"], ["score"]))
    while len(g.output):
        g.output.pop()
    g.output.append(helper.make_tensor_value_info("score", TensorProto.FLOAT, [None]))
    onnx.checker.check_model(modelo_onnx)
    return modelo_onnx


class Detector:
    nome = ""
    entrada = "tab"          # "tab" ou "seq"

    def __init__(self, semente: int = 0, **_):
        self.semente = semente
        self.d: int | None = None
        self.segundos_treino = 0.0

    def ajustar(self, X: np.ndarray, X_val: np.ndarray | None = None) -> "Detector":
        raise NotImplementedError

    def pontuar(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def para_onnx(self):
        raise NotImplementedError

    def hiperparametros(self) -> dict:
        return {}


class Regra(Detector):
    """Regra de limiar fixo: alarme quando a maior potência dos últimos 15 min passa de um limite do canal.

    O score é o próprio atributo `p_max15` (log da potência). O limite em watts de cada canal sai da
    normalização (mediana e p99 no treino) e do limiar θ escolhido na calibração — é o "if" que um
    instalador configuraria olhando o histórico do aparelho.
    """
    nome = "regra"

    def __init__(self, coluna: int = 1, **kw):
        super().__init__(**kw)
        self.coluna = coluna

    def ajustar(self, X, X_val=None):
        self.d = X.shape[1]
        return self

    def pontuar(self, X):
        return np.asarray(X[:, self.coluna], dtype=np.float64)

    def para_onnx(self):
        import onnx
        from onnx import TensorProto, helper
        idx = helper.make_tensor("coluna", TensorProto.INT64, [], [self.coluna])
        no = helper.make_node("Gather", ["x", "coluna"], ["score"], axis=1)
        g = helper.make_graph([no], "regra_limiar_fixo",
                              [helper.make_tensor_value_info("x", TensorProto.FLOAT, [None, self.d])],
                              [helper.make_tensor_value_info("score", TensorProto.FLOAT, [None])], [idx])
        m = helper.make_model(g, opset_imports=[helper.make_opsetid("", OPSET)])
        m.ir_version = 8
        onnx.checker.check_model(m)
        return m

    def hiperparametros(self):
        return {"atributo": "p_max15"}


class IForest(Detector):
    """Isolation Forest (Liu, Ting e Zhou, 2008), parâmetros padrão do artigo original."""
    nome = "if"

    def __init__(self, n_arvores: int = 100, amostras: int = 256, **kw):
        super().__init__(**kw)
        self.n_arvores, self.amostras = n_arvores, amostras

    def ajustar(self, X, X_val=None):
        from sklearn.ensemble import IsolationForest
        t = time.perf_counter()
        self.d = X.shape[1]
        self.m = IsolationForest(n_estimators=self.n_arvores, max_samples=min(self.amostras, len(X)),
                                 random_state=self.semente, n_jobs=1).fit(X)
        self.segundos_treino = time.perf_counter() - t
        return self

    def pontuar(self, X):
        return -self.m.score_samples(X)

    def para_onnx(self):
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
        o = convert_sklearn(self.m, initial_types=[("x", FloatTensorType([None, self.d]))],
                            target_opset={"": OPSET, "ai.onnx.ml": OPSET_ML},
                            options={id(self.m): {"score_samples": True}})
        return _sufixar_neg(o, "score_samples")

    def hiperparametros(self):
        return {"n_estimators": self.n_arvores, "max_samples": self.amostras}


class OCSVM(Detector):
    """One-Class SVM com kernel RBF (Schölkopf et al., 2001), atributos padronizados.

    O custo do treino cresce com o quadrado do número de amostras, então treina com uma amostra
    aleatória de `n_max` minutos do treino.
    """
    nome = "ocsvm"

    def __init__(self, nu: float = 0.01, n_max: int = 5000, **kw):
        super().__init__(**kw)
        self.nu, self.n_max = nu, n_max

    def ajustar(self, X, X_val=None):
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import OneClassSVM
        t = time.perf_counter()
        self.d = X.shape[1]
        rng = np.random.default_rng(self.semente)
        if len(X) > self.n_max:
            X = X[rng.choice(len(X), self.n_max, replace=False)]
        self.m = make_pipeline(StandardScaler(), OneClassSVM(nu=self.nu, gamma="scale")).fit(X)
        self.segundos_treino = time.perf_counter() - t
        return self

    def pontuar(self, X):
        return -self.m.decision_function(X)

    def para_onnx(self):
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
        o = convert_sklearn(self.m, initial_types=[("x", FloatTensorType([None, self.d]))],
                            target_opset={"": OPSET, "ai.onnx.ml": OPSET_ML})
        return _sufixar_neg(o, "scores")

    def hiperparametros(self):
        n_sv = int(self.m[-1].support_vectors_.shape[0]) if hasattr(self, "m") else None
        return {"kernel": "rbf", "gamma": "scale", "nu": self.nu, "amostras_treino": self.n_max,
                "vetores_suporte": n_sv}


# ----------------------------------------------------------------------------------------- redes (PyTorch)

class _Rede(Detector):
    """Base dos autoencoders: padronização dentro da rede, Adam, parada antecipada na validação.

    Para quando a perda de validação passa `paciencia` épocas sem cair pelo menos 0,1% (melhora relativa);
    o teto de épocas só existe para não rodar para sempre. Volta aos pesos da melhor época."""
    epocas_max = 200
    paciencia = 5
    melhora_min = 1e-3
    lote = 512
    taxa = 1e-3

    def __init__(self, epocas_max: int | None = None, threads: int | None = None, **kw):
        super().__init__(**kw)
        if epocas_max is not None:
            self.epocas_max = epocas_max
        self.threads = threads
        self.historico: list[tuple[float, float]] = []

    def _rede(self, mu, sd):
        raise NotImplementedError

    def ajustar(self, X, X_val=None):
        import torch
        t0 = time.perf_counter()
        if self.threads:
            torch.set_num_threads(self.threads)
        torch.manual_seed(self.semente)
        rng = np.random.default_rng(self.semente)
        X = np.asarray(X, np.float32)
        eixos = tuple(range(X.ndim - 1))
        mu = X.mean(axis=eixos)
        sd = X.std(axis=eixos)
        sd = np.where(sd < 1e-3, 1.0, sd).astype(np.float32)   # atributo constante no treino: não escala
        self.d = X.shape[-1]
        self.net = self._rede(torch.tensor(mu), torch.tensor(sd))
        opt = torch.optim.Adam(self.net.parameters(), lr=self.taxa)
        Xt = torch.tensor(X)
        Xv = torch.tensor(np.asarray(X_val, np.float32)) if X_val is not None and len(X_val) else None
        melhor, estado, ruins = np.inf, None, 0
        for _ in range(self.epocas_max):
            self.net.train()
            ordem = torch.tensor(rng.permutation(len(Xt)))
            soma = 0.0
            for i in range(0, len(Xt), self.lote):
                lote = Xt[ordem[i:i + self.lote]]
                perda = self.net(lote).mean()
                opt.zero_grad()
                perda.backward()
                opt.step()
                soma += float(perda.detach()) * len(lote)
            perda_tr = soma / len(Xt)
            perda_val = float(self._pontuar_t(Xv).mean()) if Xv is not None else perda_tr
            self.historico.append((perda_tr, perda_val))
            if perda_val < melhor * (1 - self.melhora_min):
                melhor, ruins = perda_val, 0
                estado = {k: v.detach().clone() for k, v in self.net.state_dict().items()}
            else:
                ruins += 1
                if ruins >= self.paciencia:
                    break
        if estado is not None:
            self.net.load_state_dict(estado)
        self.net.eval()
        self.segundos_treino = time.perf_counter() - t0
        return self

    def _pontuar_t(self, Xt, lote: int = 4096):
        import torch
        self.net.eval()
        with torch.no_grad():
            return torch.cat([self.net(Xt[i:i + lote]) for i in range(0, len(Xt), lote)])

    def pontuar(self, X):
        import torch
        if len(X) == 0:
            return np.zeros(0)
        return self._pontuar_t(torch.tensor(np.asarray(X, np.float32))).numpy().astype(np.float64)

    def _exemplo(self):
        raise NotImplementedError

    def para_onnx(self):
        """Exporta com o exportador TorchScript (`dynamo=False`), que respeita o opset 17 e gera o nó LSTM
        nativo do ONNX. O exportador novo (`dynamo=True`) só sai em opset 18 nesta versão do torch
        (a conversão para 17 falha); ver DIARIO.md, B5."""
        import io
        import warnings

        import onnx
        import torch
        exemplo = self._exemplo()
        buf = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            torch.onnx.export(self.net, (exemplo,), buf, input_names=["x"], output_names=["score"],
                              opset_version=OPSET, dynamo=False,
                              dynamic_axes={"x": {0: "lote"}, "score": {0: "lote"}})
        m = onnx.load_from_string(buf.getvalue())
        onnx.checker.check_model(m)
        return m

    def hiperparametros(self):
        return {"epocas_max": self.epocas_max, "paciencia": self.paciencia, "melhora_min_relativa": self.melhora_min,
                "lote": self.lote,
                "taxa_aprendizado": self.taxa, "epocas_rodadas": len(self.historico),
                "perda_val_final": round(min(h[1] for h in self.historico), 6) if self.historico else None}


def _modulos():
    import torch
    from torch import nn

    class AE(nn.Module):
        """Autoencoder denso d → 32 → 8 → 32 → d. Saída: erro quadrático médio da reconstrução."""

        def __init__(self, d, mu, sd, h1=32, h2=8):
            super().__init__()
            self.register_buffer("mu", mu)
            self.register_buffer("sd", sd)
            self.enc = nn.Sequential(nn.Linear(d, h1), nn.ReLU(), nn.Linear(h1, h2), nn.ReLU())
            self.dec = nn.Sequential(nn.Linear(h2, h1), nn.ReLU(), nn.Linear(h1, d))

        def forward(self, x):
            z = (x - self.mu) / self.sd
            r = self.dec(self.enc(z))
            return ((r - z) ** 2).mean(dim=1)

    class LSTMAE(nn.Module):
        """LSTM autoencoder (Malhotra et al., 2016): codifica L minutos num vetor de h e reconstrói a sequência."""

        def __init__(self, d, mu, sd, h=32):
            super().__init__()
            self.register_buffer("mu", mu)
            self.register_buffer("sd", sd)
            self.enc = nn.LSTM(d, h, batch_first=True)
            self.dec = nn.LSTM(h, h, batch_first=True)
            self.saida = nn.Linear(h, d)

        def forward(self, x):
            z = (x - self.mu) / self.sd
            _, (hn, _) = self.enc(z)
            rep = hn[-1].unsqueeze(1).expand(-1, z.shape[1], -1)
            y, _ = self.dec(rep)
            r = self.saida(y)
            return ((r - z) ** 2).mean(dim=(1, 2))

    return AE, LSTMAE


class AE(_Rede):
    nome = "ae"

    def _rede(self, mu, sd):
        return _modulos()[0](self.d, mu, sd)

    def _exemplo(self):
        import torch
        return torch.zeros(2, self.d)

    def hiperparametros(self):
        return {"camadas": [self.d, 32, 8, 32, self.d], "ativacao": "ReLU", **super().hiperparametros()}


class LSTMAE(_Rede):
    nome = "lstm_ae"
    entrada = "seq"
    lote = 256
    epocas_max = 150

    def __init__(self, L: int = 60, passo_treino: int = 5, h: int = 32, **kw):
        super().__init__(**kw)
        self.L, self.passo_treino, self.h = L, passo_treino, h

    def _rede(self, mu, sd):
        return _modulos()[1](self.d, mu, sd, self.h)

    def _exemplo(self):
        import torch
        return torch.zeros(2, self.L, self.d)

    def hiperparametros(self):
        return {"L_minutos": self.L, "oculto": self.h, "passo_treino_min": self.passo_treino,
                **super().hiperparametros()}


MODELOS = {c.nome: c for c in (Regra, IForest, OCSVM, AE, LSTMAE)}


def criar(nome: str, **kw) -> Detector:
    return MODELOS[nome](**kw)
