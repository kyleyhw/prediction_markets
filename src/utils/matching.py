from difflib import SequenceMatcher
from typing import List, Tuple, Dict
import pandas as pd

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def match_events(events_a: List[Dict], events_b: List[Dict], threshold: float = 0.6) -> List[Tuple[Dict, Dict, float]]:
    """
    Match events from two lists based on title similarity.
    
    Args:
        events_a: List of event dictionaries (e.g. from Polymarket).
        events_b: List of event dictionaries (e.g. from Kalshi).
        threshold: Similarity threshold (0.0 to 1.0).
        
    Returns:
        List of tuples: (event_a, event_b, similarity_score)
    """
    matches = []
    used_b = set()
    
    # Simple greedy matching
    for event_a in events_a:
        best_match = None
        best_score = 0.0
        best_idx = -1
        
        for idx, event_b in enumerate(events_b):
            if idx in used_b:
                continue
            
            score = similarity(event_a['event_name'], event_b['event_name'])
            if score > best_score:
                best_score = score
                best_match = event_b
                best_idx = idx
        
        if best_score >= threshold:
            matches.append((event_a, best_match, best_score))
            used_b.add(best_idx)
            
    return matches
