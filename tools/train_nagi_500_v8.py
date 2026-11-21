import argparse
import json
import random
import torch
import torch.nn as nn
import torch.optim as optim
from pathlib import Path

# --- Architecture ---
class Encoder(nn.Module):
    def __init__(self, vocab_size, emb_dim, hid_dim):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.rnn = nn.GRU(emb_dim, hid_dim, batch_first=True, bidirectional=True)
        self.fc = nn.Linear(hid_dim * 2, hid_dim)

    def forward(self, src):
        # src: [batch, src_len]
        embedded = self.embedding(src)
        outputs, hidden = self.rnn(embedded)
        # Concat bidirectional hidden states for decoder initial state
        hidden = torch.tanh(self.fc(torch.cat((hidden[-2,:,:], hidden[-1,:,:]), dim=1)))
        return outputs, hidden

class Attention(nn.Module):
    def __init__(self, hid_dim):
        super().__init__()
        self.attn = nn.Linear(hid_dim * 3, hid_dim)
        self.v = nn.Linear(hid_dim, 1, bias=False)

    def forward(self, hidden, encoder_outputs):
        # hidden: [batch, hid_dim], encoder_outputs: [batch, src_len, hid_dim*2]
        batch_size = encoder_outputs.shape[0]
        src_len = encoder_outputs.shape[1]
        
        hidden = hidden.unsqueeze(1).repeat(1, src_len, 1)
        energy = torch.tanh(self.attn(torch.cat((hidden, encoder_outputs), dim=2)))
        attention = self.v(energy).squeeze(2)
        return torch.softmax(attention, dim=1)

class PointerDecoder(nn.Module):
    def __init__(self, vocab_size, emb_dim, hid_dim):
        super().__init__()
        self.vocab_size = vocab_size
        self.attention = Attention(hid_dim)
        self.embedding = nn.Embedding(vocab_size, emb_dim, padding_idx=0)
        self.rnn = nn.GRU(hid_dim * 2 + emb_dim, hid_dim, batch_first=True)
        self.fc_out = nn.Linear(hid_dim * 3 + emb_dim, vocab_size)
        # Pointer mechanism: p_gen = sigmoid(W * [context, state, input])
        self.p_gen = nn.Linear(hid_dim * 3 + emb_dim, 1)

    def forward(self, input, hidden, encoder_outputs):
        input = input.unsqueeze(1) # [batch, 1]
        embedded = self.embedding(input) # [batch, 1, emb_dim]
        
        a = self.attention(hidden, encoder_outputs).unsqueeze(1) # [batch, 1, src_len]
        context = torch.bmm(a, encoder_outputs) # [batch, 1, hid_dim*2]
        
        rnn_input = torch.cat((embedded, context), dim=2)
        output, hidden = self.rnn(rnn_input, hidden.unsqueeze(0))
        output = output.squeeze(1)
        context = context.squeeze(1)
        embedded = embedded.squeeze(1)
        
        # Vocabulary distribution
        pred = self.fc_out(torch.cat((output, context, embedded), dim=1))
        vocab_dist = torch.softmax(pred, dim=1)
        
        # Pointer generation probability
        p_gen = torch.sigmoid(self.p_gen(torch.cat((context, hidden.squeeze(0), embedded), dim=1)))
        
        # Extend vocab distribution with copy distribution
        attn_dist = a.squeeze(1) # [batch, src_len]
        # Scatter attention weights to vocab space
        copy_dist = torch.zeros_like(vocab_dist).scatter_add(1, input, attn_dist)
        
        final_dist = p_gen * vocab_dist + (1 - p_gen) * copy_dist
        return final_dist, hidden, p_gen

class Seq2Seq(nn.Module):
    def __init__(self, encoder, decoder, device):
        super().__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.device = device

    def forward(self, src, trg, teacher_forcing_ratio=0.5):
        batch_size = src.shape[0]
        trg_len = trg.shape[1]
        vocab_size = self.decoder.vocab_size
        
        outputs = torch.zeros(batch_size, trg_len, vocab_size).to(self.device)
        encoder_outputs, hidden = self.encoder(src)
        input = trg[:, 0]
        
        for t in range(1, trg_len):
            output, hidden, _ = self.decoder(input, hidden, encoder_outputs)
            outputs[:, t, :] = output
            teacher_force = random.random() < teacher_forcing_ratio
            top1 = output.argmax(1)
            input = trg[:, t] if teacher_force else top1
            
        return outputs

    def generate(self, src, max_len=20, sos_idx=2, eos_idx=3):
        # Free generation for evaluation
        encoder_outputs, hidden = self.encoder(src)
        input = torch.tensor([sos_idx] * src.shape[0]).to(self.device)
        
        preds = []
        for _ in range(max_len):
            output, hidden, _ = self.decoder(input, hidden, encoder_outputs)
            top1 = output.argmax(1)
            preds.append(top1)
            input = top1
            if (top1 == eos_idx).all(): break
            
        return torch.stack(preds, dim=1)

# --- Helper Functions ---
def save_checkpoint(state, filename):
    torch.save(state, filename)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=str, required=True)
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--steps", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    # 1. Set Seed (Same as v7)
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 2. Load Data (Mocked for brevity, replace with actual v7 data loader)
    # data = json.loads(Path(args.data).read_text())
    # train_loader = ...
    
    # 3. Init Model
    HID_DIM = 128
    EMB_DIM = 128
    VOCAB_SIZE = 500 # Example, should match v7
    enc = Encoder(VOCAB_SIZE, EMB_DIM, HID_DIM)
    dec = PointerDecoder(VOCAB_SIZE, EMB_DIM, HID_DIM)
    model = Seq2Seq(enc, dec, device).to(device)
    
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    
    # 4. Training Loop (Mocked)
    best_val_loss = float('inf')
    for step in range(args.steps):
        model.train()
        # Mocked training step (Replace with actual batch iterator)
        # loss = ...
        # optimizer.zero_grad()
        # loss.backward()
        # optimizer.step()
        
        if step % 50 == 0:
            # Validation logic
            pass

    # 5. Save Checkpoint
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "step_500.pt"
    
    save_checkpoint({
        'step': args.steps,
        'arch': 'seq2seq_attn_pointer',
        'vocab_size': VOCAB_SIZE,
        'model_state': model.state_dict(),
        'optimizer_state': optimizer.state_dict(),
        'best_val_state': None # Fill with actual best val state
    }, ckpt_path)
    print(f"Saved checkpoint to {ckpt_path}")

if __name__ == "__main__":
    main()
