import React, { useState, useEffect, useRef } from 'react';
import { Upload, Trash2, Replace, Plus, Image as ImageIcon, FileText, GripVertical } from 'lucide-react';
import DOMPurify from 'dompurify';
import './App.css';
import type { Card } from './types';

/**
 * Generate canonical card image URL on aeonsend.wiki.gg matching aeons-end-turn-order pattern.
 */
const getCardImageUrl = (cardName: string): string => {
  return `https://aeonsend.wiki.gg/images/${encodeURIComponent(cardName.replace(/ /g, '_'))}.jpg`;
};

/**
 * Sort cards ascending by numeric cost, with secondary alphabetical sort by name.
 */
const sortCardsByCost = (cards: Card[]): Card[] => {
  return [...cards].sort((a, b) => {
    const costA = parseInt(String(a.cost), 10) || 0;
    const costB = parseInt(String(b.cost), 10) || 0;
    if (costA !== costB) {
      return costA - costB;
    }
    return a.name.localeCompare(b.name);
  });
};

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
// Stop shrinking below this long edge; card text becomes unreadable for the scanner.
const MIN_LONG_EDGE_PX = 1024;

/**
 * Re-encode an oversized image as JPEG, scaling it down until it fits under MAX_UPLOAD_BYTES.
 * Throws if the image can't be decoded or can't be made small enough.
 */
const shrinkImage = async (file: File): Promise<File> => {
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  try {
    let width = bitmap.width;
    let height = bitmap.height;
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Canvas 2D context unavailable');

    for (;;) {
      canvas.width = width;
      canvas.height = height;
      // JPEG has no alpha; fill white so transparent PNG regions don't turn black
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(bitmap, 0, 0, width, height);

      const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9));
      if (!blob) throw new Error('Failed to encode image');
      if (blob.size <= MAX_UPLOAD_BYTES) {
        const name = file.name.replace(/\.[^.]*$/, '') + '.jpg';
        return new File([blob], name, { type: 'image/jpeg' });
      }

      if (Math.max(width, height) * 0.75 < MIN_LONG_EDGE_PX) {
        throw new Error('Image is too large to shrink under 10MB');
      }
      width = Math.round(width * 0.75);
      height = Math.round(height * 0.75);
    }
  } finally {
    bitmap.close();
  }
};

/**
 * Main application component for Aeon's End Supply Scanner.
 * 
 * Manages:
 * - Current supply card list state
 * - Database loading and caching
 * - Image scanning workflows via /api/scan
 * - Direct card manipulation (swap, delete, add, drag-and-drop reorder)
 * - Automatic URL query parameter synchronization (?cards=...)
 */
function App() {
  // Current active supply cards displayed on the board
  const [supply, setSupply] = useState<Card[]>([]);
  // Canonical database of all available supply cards
  const [db, setDb] = useState<Card[]>([]);
  // Scan status indicator
  const [isScanning, setIsScanning] = useState(false);
  // Modal visibility for card search/selection
  const [modalOpen, setModalOpen] = useState(false);
  // Target index being swapped, or null when appending a new card
  const [swapTarget, setSwapTarget] = useState<number | null>(null);
  // Text search query for filtering cards in picker modal
  const [search, setSearch] = useState('');
  // Visual drag-and-drop indicator
  const [isDragging, setIsDragging] = useState(false);
  // Flag indicating initial DB load and URL param hydration is complete
  const [isInitialized, setIsInitialized] = useState(false);
  // Toggle between card text descriptions and card images from aeonsend.wiki.gg (defaults to images)
  const [showImages, setShowImages] = useState(true);
  // Indices tracking card reordering drag-and-drop interactions
  const [draggedCardIndex, setDraggedCardIndex] = useState<number | null>(null);
  const [dragOverCardIndex, setDragOverCardIndex] = useState<number | null>(null);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Fetch canonical card list and restore state from URL query parameters on mount
  useEffect(() => {
    fetch('/api/cards')
      .then(res => res.json())
      .then((data: Card[]) => {
        setDb(data);
        // Load initial state from URL '?cards=idx1,idx2,...' using canonical array indices
        const params = new URLSearchParams(window.location.search);
        const cardsParam = params.get('cards');
        if (cardsParam) {
          const indices = cardsParam.split(',')
            .map(s => parseInt(s.trim(), 10))
            .filter(idx => Number.isInteger(idx) && idx >= 0 && idx < data.length);
          const initialCards = indices.map(idx => data[idx]);
          setSupply(initialCards);
        }
        setIsInitialized(true);
      })
      .catch(err => {
        console.error("Error loading DB", err);
        setIsInitialized(true);
      });
  }, []);

  // Automatically synchronize supply cards to URL query string (?cards=0,1,...)
  useEffect(() => {
    if (!isInitialized) return;
    const currentParams = new URLSearchParams(window.location.search);
    if (supply.length > 0) {
      const indices = supply.map(c => c.index).join(',');
      currentParams.set('cards', indices);
    } else {
      currentParams.delete('cards');
    }
    const newQuery = currentParams.toString();
    const newUrl = newQuery ? `${window.location.pathname}?${newQuery}` : window.location.pathname;
    window.history.replaceState({}, '', newUrl);
  }, [supply, isInitialized]);

  /**
   * Common file processor for both file input selection and drag-and-drop.
   */
  const processFile = async (file: File) => {
    const validTypes = ['image/jpeg', 'image/png', 'image/webp'];
    if (!validTypes.includes(file.type)) {
      alert("Unsupported image format. Please use JPEG, PNG, or WebP.");
      return;
    }

    setIsScanning(true);

    try {
      if (file.size > MAX_UPLOAD_BYTES) {
        file = await shrinkImage(file);
      }

      const formData = new FormData();
      formData.append('image', file);

      const res = await fetch('/api/scan', {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => null);
        throw new Error(errJson?.detail || "Scan failed");
      }
      const data = await res.json();
      const detectedCards: Card[] = data.detected_cards || [];
      const unmatchedCards: string[] = data.unmatched_cards || [];
      const totalDetected: number = data.total_detected ?? (detectedCards.length + unmatchedCards.length);

      if (detectedCards.length > 0) {
        setSupply(prev => [...prev, ...detectedCards]);
      }

      if (totalDetected === 0) {
        alert("No supply cards detected in the image.");
      } else if (unmatchedCards.length > 0) {
        const unmatchedList = unmatchedCards.map(name => `• ${name}`).join('\n');
        alert(
          `Detected ${totalDetected} card${totalDetected === 1 ? '' : 's'}` +
          (detectedCards.length > 0 ? ` (${detectedCards.length} added to supply)` : '') +
          `.\n\n${unmatchedCards.length} card${unmatchedCards.length === 1 ? '' : 's'} could not be found in the database:\n${unmatchedList}`
        );
      } else {
        alert(`Detected ${totalDetected} card${totalDetected === 1 ? '' : 's'} (all matched and added to supply).`);
      }
    } catch (err: unknown) {
      console.error("Scan error:", err);
      const msg = err instanceof Error ? err.message : "Failed to scan image.";
      alert(`Scan failed: ${msg}`);
    } finally {
      setIsScanning(false);
    }
  };

  /**
   * Submit chosen image file to /api/scan and append detected cards to supply.
   */
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await processFile(file);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    if (e.dataTransfer.types.includes('Files')) {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
    }
  };

  const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    if (e.dataTransfer.types.includes('Files')) {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsDragging(false);
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const file = e.dataTransfer.files?.[0];
    if (file) {
      await processFile(file);
    }
  };

  // Card drag-and-drop reordering handlers
  const handleCardDragStart = (e: React.DragEvent<HTMLDivElement>, index: number) => {
    e.dataTransfer.setData('application/x-card-index', index.toString());
    e.dataTransfer.effectAllowed = 'move';
    setDraggedCardIndex(index);
  };

  const handleCardDragOver = (e: React.DragEvent<HTMLDivElement>, index: number) => {
    if (e.dataTransfer.types.includes('application/x-card-index')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (dragOverCardIndex !== index) {
        setDragOverCardIndex(index);
      }
    }
  };

  const handleCardDragLeave = (e: React.DragEvent<HTMLDivElement>, index: number) => {
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    if (dragOverCardIndex === index) {
      setDragOverCardIndex(null);
    }
  };

  const handleCardDrop = (e: React.DragEvent<HTMLDivElement>, targetIndex: number) => {
    e.preventDefault();
    const srcIndexStr = e.dataTransfer.getData('application/x-card-index');
    const srcIndex = parseInt(srcIndexStr, 10);
    if (Number.isInteger(srcIndex) && srcIndex >= 0 && srcIndex < supply.length && srcIndex !== targetIndex) {
      setSupply(prev => {
        const next = [...prev];
        const [moved] = next.splice(srcIndex, 1);
        next.splice(targetIndex, 0, moved);
        return next;
      });
    }
    setDraggedCardIndex(null);
    setDragOverCardIndex(null);
  };

  const handleCardDragEnd = () => {
    setDraggedCardIndex(null);
    setDragOverCardIndex(null);
  };

  // Open modal to swap card at specific index
  const openSwap = (index: number) => {
    setSwapTarget(index);
    setSearch('');
    setModalOpen(true);
  };

  // Open modal to add a new card slot
  const openAdd = () => {
    setSwapTarget(null);
    setSearch('');
    setModalOpen(true);
  };

  // Remove a card from the supply board
  const deleteCard = (index: number) => {
    setSupply(prev => prev.filter((_, i) => i !== index));
  };

  // Select card from picker modal (either swap existing or append)
  const selectCard = (card: Card) => {
    if (swapTarget !== null) {
      setSupply(prev => {
        const next = [...prev];
        next[swapTarget] = card;
        return next;
      });
    } else {
      setSupply(prev => [...prev, card]);
    }
    setModalOpen(false);
  };

  // Clear all cards from the supply board
  const clearAll = () => {
    setSupply([]);
  };

  return (
    <div className="container">
      {/* Header bar with title */}
      <header>
        <h1>Aeon's End Supply Scanner</h1>
      </header>

      {/* Image upload / camera dropzone area */}
      <div 
        className={`scanner-area ${isDragging ? 'drag-over' : ''}`}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={handleDragOver}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input 
          type="file" 
          accept="image/*" 
          ref={fileInputRef} 
          style={{ display: 'none' }}
          onChange={handleFileUpload}
        />
        {isScanning ? (
          <p>Scanning... Please wait.</p>
        ) : (
          <div>
            <Upload size={48} />
            <h2>{isDragging ? 'Drop image here to scan' : 'Click or drop image to scan supply'}</h2>
            <p style={{ color: '#888', fontSize: '0.85rem', margin: '4px 0 0' }}>Supports JPEG, PNG, WebP (images over 10MB are shrunk automatically)</p>
          </div>
        )}
      </div>

      {/* Action controls under dropzone and above card grid */}
      <div className="supply-actions">
        <button 
          className={`toggle-view-btn ${showImages ? 'active' : ''}`}
          onClick={() => setShowImages(prev => !prev)}
          title={showImages ? "Show text descriptions" : "Show card images from aeonsend.wiki.gg"}
        >
          {showImages ? (
            <>
              <FileText size={16} />
              Show Descriptions
            </>
          ) : (
            <>
              <ImageIcon size={16} />
              Show Images
            </>
          )}
        </button>
        <button 
          className="clear-btn" 
          onClick={clearAll} 
          disabled={supply.length === 0}
          title="Clear all cards from supply"
        >
          <Trash2 size={16} />
          Clear All
        </button>
      </div>

      {/* Responsive card grid displaying detected or added supply cards */}
      <div className="card-grid">
        {supply.map((card, idx) => {
          const isDraggingThis = draggedCardIndex === idx;
          const isDragOverThis = dragOverCardIndex === idx;
          return (
            <div 
              key={`${card.index}-${idx}`} 
              className={`card-slot ${showImages ? 'image-only' : ''} ${isDraggingThis ? 'is-dragging' : ''} ${isDragOverThis ? 'is-drag-over' : ''}`}
              draggable
              onDragStart={(e) => handleCardDragStart(e, idx)}
              onDragOver={(e) => handleCardDragOver(e, idx)}
              onDragLeave={(e) => handleCardDragLeave(e, idx)}
              onDrop={(e) => handleCardDrop(e, idx)}
              onDragEnd={handleCardDragEnd}
            >
              <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                <span className="drag-handle" title="Drag card to reorder"><GripVertical size={16}/></span>
                <button className="icon-btn" onClick={() => openSwap(idx)} title="Swap"><Replace size={16}/></button>
                <button className="icon-btn delete" onClick={() => deleteCard(idx)} title="Delete"><Trash2 size={16}/></button>
              </div>
              {showImages ? (
                <div className="card-image-container">
                  <a 
                    href={`https://aeonsend.wiki.gg/wiki/${encodeURIComponent(card.name.replace(/ /g, '_'))}`} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    title={`View ${card.name} on Aeon's End Wiki`}
                    draggable={false}
                  >
                    <img 
                      src={getCardImageUrl(card.name)} 
                      alt={card.name}
                      loading="lazy"
                      className="card-image"
                      draggable={false}
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  </a>
                </div>
              ) : (
                <>
                  <h3>{card.name}</h3>
                  <p>{card.type} | Cost: {card.cost}</p>
                  <p><em>{card.expansion}</em></p>
                  {/* Sanitize HTML markup (<b>, <i>, formatting) before rendering */}
                  <div 
                    className="card-effect"
                    dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(card.effect) }}
                  />
                </>
              )}
            </div>
          );
        })}
        {/* Slot to manually append an additional card to the supply layout */}
        <div className={`card-slot add-card-slot ${showImages ? 'image-only' : ''}`} onClick={openAdd}>
          <Plus size={32} />
          <p>Add Card</p>
        </div>
      </div>

      {/* Card picker modal for manual addition or card swapping */}
      {modalOpen && (
        <div className="modal-overlay" onClick={() => setModalOpen(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h2>{swapTarget !== null ? 'Swap Card' : 'Add Card'}</h2>
              <button 
                className="modal-close-btn" 
                onClick={() => setModalOpen(false)} 
                title="Close"
                type="button"
              >
                ✕
              </button>
            </div>
            <input 
              type="text" 
              className="search-input" 
              placeholder="Search by words in card title..." 
              value={search}
              onChange={e => setSearch(e.target.value)}
              autoFocus
            />
            <div className="modal-list">
              {(() => {
                const terms = search
                  .trim()
                  .toLowerCase()
                  .split(/\s+/)
                  .filter(t => t.length > 0);
                if (terms.length === 0) {
                  return <p className="modal-empty-hint">Type a card name to search...</p>;
                }
                const matches = sortCardsByCost(
                  db.filter(c => {
                    const lower = c.name.toLowerCase();
                    const cleaned = lower.replace(/[-_']/g, ' ');
                    return terms.every(term => lower.includes(term) || cleaned.includes(term));
                  })
                );
                if (matches.length === 0) {
                  return <p className="modal-empty-hint">No cards matching "{search.trim()}"</p>;
                }
                return matches.slice(0, 50).map(c => (
                  <div key={c.index} className="modal-list-item" onClick={() => selectCard(c)}>
                    <strong>{c.name}</strong> - {c.type} (Cost: {c.cost})
                  </div>
                ));
              })()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
