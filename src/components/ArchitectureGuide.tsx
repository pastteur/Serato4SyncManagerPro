import React from 'react';
import { BookOpen, ShieldAlert, Cpu, HardDrive, RefreshCw, Key } from 'lucide-react';

export const ArchitectureGuide: React.FC = () => {
  return (
    <div className="bg-serato-dark border border-serato-cardBorder rounded-xl p-5 shadow-2xl space-y-4">
      <div className="pb-3 border-b border-serato-cardBorder">
        <h3 className="text-base font-bold text-white flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-serato-gold" />
          <span>Manual de Arquitetura & Engenharia do Serato DJ Pro 4</span>
        </h3>
        <p className="text-xs text-serato-muted">
          Compreenda os pilares que garantem zero faixas laranjas, blindagem contra perda de dados e máxima velocidade.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Pilar 1: Normalização Unicode NFC */}
        <div className="bg-serato-card border border-serato-cardBorder p-4 rounded-lg space-y-2">
          <div className="flex items-center space-x-2 text-serato-cyan font-bold text-xs uppercase tracking-wide">
            <Key className="w-4 h-4" />
            <span>1. Normalização Unicode NFC (Fim do Bug das Faixas Laranjas)</span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">
            O macOS Tahoe/APFS decompõe caracteres acentuados (<code className="text-amber-300">NFD</code>: "Moda" + "˜" + "o"). O Serato DJ Pro 4 exige strings pré-compostas (<code className="text-emerald-400">NFC</code>: "Modão"). O motor aplica <code className="text-serato-cyan">unicodedata.normalize('NFC')</code> em todas as tags TLV, garantindo que axé, forró e sertanejo nunca fiquem offline.
          </p>
        </div>

        {/* Pilar 2: Trava Matemática Anti-Falso-Positivo */}
        <div className="bg-serato-card border border-serato-cardBorder p-4 rounded-lg space-y-2">
          <div className="flex items-center space-x-2 text-serato-gold font-bold text-xs uppercase tracking-wide">
            <Cpu className="w-4 h-4" />
            <span>2. Trava Matemática Anti-Falso-Positivo</span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">
            Um cache local em <code className="text-serato-gold">~/.serato_sync_cache.json</code> armazena a chave do caminho real cruzando duas métricas de hardware: <strong>[Quantidade de Arquivos]</strong> e <strong>[Tamanho em Bytes]</strong>. Se os números baterem com o ciclo anterior, a escrita física da crate é pulada (Smart Crate Writing), poupando a vida útil do HD.
          </p>
        </div>

        {/* Pilar 3: Banco master.sqlite Intacto */}
        <div className="bg-serato-card border border-serato-cardBorder p-4 rounded-lg space-y-2">
          <div className="flex items-center space-x-2 text-serato-neonGreen font-bold text-xs uppercase tracking-wide">
            <ShieldAlert className="w-4 h-4 text-serato-neonGreen" />
            <span>3. Proteção Total de Histórico (master.sqlite)</span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">
            O banco SQLite central localizado em <code className="text-serato-neonGreen">~/Library/Application Support/Serato/Library/master.sqlite</code> armazena o histórico de execuções, faixas azuis tocadas, beatgrids e BPM. O sincronizador atua <strong>estritamente</strong> no sistema de arquivos binários (<code className="text-slate-300">Subcrates/*.crate</code>), nunca apagando ou resetando o banco de dados.
          </p>
        </div>

        {/* Pilar 4: Caminhos Relativos e Escrita Atômica */}
        <div className="bg-serato-card border border-serato-cardBorder p-4 rounded-lg space-y-2">
          <div className="flex items-center space-x-2 text-serato-orange font-bold text-xs uppercase tracking-wide">
            <HardDrive className="w-4 h-4" />
            <span>4. Caminhos Relativos & Gravação Atômica</span>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">
            As tags <code className="text-serato-cyan">ptrk</code> gravam apenas o caminho relativo à raiz do disco (<code className="text-slate-300">Music/MP3/Sertanejo/41/musica.mp3</code>). Além disso, toda escrita é gerada em arquivo temporário <code className="text-amber-300">.tmp</code> e substituída via <code className="text-serato-cyan">shutil.move()</code> apenas após o encerramento seguro do buffer.
          </p>
        </div>
      </div>
    </div>
  );
};
