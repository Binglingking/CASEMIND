---
name: Celestial Intelligence
colors:
  surface: '#141218'
  surface-dim: '#141218'
  surface-bright: '#3b383e'
  surface-container-lowest: '#0f0d13'
  surface-container-low: '#1d1b20'
  surface-container: '#211f24'
  surface-container-high: '#2b292f'
  surface-container-highest: '#36343a'
  on-surface: '#e6e0e9'
  on-surface-variant: '#cbc4d2'
  inverse-surface: '#e6e0e9'
  inverse-on-surface: '#322f35'
  outline: '#948e9c'
  outline-variant: '#494551'
  surface-tint: '#cfbcff'
  primary: '#cfbcff'
  on-primary: '#381e72'
  primary-container: '#6750a4'
  on-primary-container: '#e0d2ff'
  inverse-primary: '#6750a4'
  secondary: '#cdc0e9'
  on-secondary: '#342b4b'
  secondary-container: '#4d4465'
  on-secondary-container: '#bfb2da'
  tertiary: '#e7c365'
  on-tertiary: '#3e2e00'
  tertiary-container: '#c9a74d'
  on-tertiary-container: '#503d00'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#e9ddff'
  primary-fixed-dim: '#cfbcff'
  on-primary-fixed: '#22005d'
  on-primary-fixed-variant: '#4f378a'
  secondary-fixed: '#e9ddff'
  secondary-fixed-dim: '#cdc0e9'
  on-secondary-fixed: '#1f1635'
  on-secondary-fixed-variant: '#4b4263'
  tertiary-fixed: '#ffdf93'
  tertiary-fixed-dim: '#e7c365'
  on-tertiary-fixed: '#241a00'
  on-tertiary-fixed-variant: '#594400'
  background: '#141218'
  on-background: '#e6e0e9'
  surface-variant: '#36343a'
typography:
  display:
    fontFamily: Manrope
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  h1:
    fontFamily: Manrope
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  h2:
    fontFamily: Manrope
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: 0em
  body-lg:
    fontFamily: Manrope
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: 0.01em
  body-md:
    fontFamily: Manrope
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: 0.01em
  label-caps:
    fontFamily: Space Grotesk
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1.5'
    letterSpacing: 0.1em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 40px
  gutter: 24px
  margin: 32px
---

## Brand & Style
The brand personality is authoritative yet ethereal, blending the precision of high-end aerospace interfaces with the approachable intelligence of modern AI. This design system targets a sophisticated user base that values both aesthetic beauty and functional clarity.

The visual style is a fusion of **Minimalism** and **Glassmorphism**, referred to as "Elegant Tech." It relies on depth created through transparency and light rather than heavy shadows. The emotional response is one of calm focus, luxury, and technological advancement. All elements should feel like they are floating in a vast, organized digital space, utilizing "obsidian" surfaces and "luminescent" boundaries.

## Colors
The palette is rooted in "Deep Obsidian" to provide an infinite canvas that reduces eye strain. Containers use "Midnight Blue" to create subtle structural differentiation without breaking the dark immersion. 

Accent colors are used sparingly for interactive elements and data visualization. The "Celestial Blue" and "Soft Indigo" should be applied primarily as gradients or soft outer glows (bloom effects). High-contrast white text ensures maximum readability against the dark backgrounds, while muted slate tones handle secondary information.

## Typography
This design system utilizes **Manrope** for its primary typeface, chosen for its modern, balanced, and premium feel. To emphasize the "Tech" aspect of the aesthetic, **Space Grotesk** is used for labels and small data points to provide a subtle geometric, futuristic edge. 

Generous letter spacing is applied to body text and labels to maintain the "airy" feel within data-dense layouts. Headlines should remain tight and impactful.

## Layout & Spacing
The layout follows a **Fluid Grid** model with a 12-column structure for desktop. To achieve a "data-dense but airy" layout, we use a 4px baseline grid but enforce large outer margins and internal "breathing room" (padding) within containers. 

Section dividers should be avoided in favor of whitespace or the 1px luminescent borders. Grouped data should use tight internal spacing (8px) but be surrounded by generous external margins (40px+) to maintain a clean hierarchy.

## Elevation & Depth
Elevation is expressed through **Glassmorphism** and tonal layering. Rather than traditional shadows, depth is achieved by:
1. **Z-axis Layering:** Using the secondary midnight blue for raised surfaces.
2. **Backdrop Blur:** Modal windows and floating menus must use a `20px` to `40px` blur with a semi-transparent background (`rgba(16, 20, 29, 0.7)`).
3. **Luminescent Borders:** A 1px solid border with a very low-opacity white or a hint of the accent color creates a "lit from within" effect.
4. **Subtle Glows:** Active or hovered states should emit a soft, diffused `15px` radial glow using the accent colors to simulate light emitting from the component.

## Shapes
The shape language is sophisticated and approachable. We use **Rounded** (Level 2) settings as the standard. 
- Standard buttons and input fields: `8px` (rounded).
- Primary containers and cards: `16px` (rounded-xl).
- Large dashboard sections: `24px`.

The consistency of these soft corners is vital to offset the "sharpness" of the dark theme and high-contrast typography.

## Components
- **Buttons:** Primary buttons use a gradient from Celestial Blue to Soft Indigo. Secondary buttons are "Ghost" style with the 1px luminescent border. Hovering any button triggers a transition to a more intense glow and a slight (2%) scale increase.
- **Cards:** Use the Midnight Blue background with a `1px` border. For high-priority content, add a subtle top-border gradient of 1px thickness.
- **Inputs:** Darker than the container background, using a focus state that illuminates the entire border in Celestial Blue with a soft `4px` outer glow.
- **Chips/Badges:** Use Space Grotesk in all-caps. Backgrounds should be highly desaturated versions of the status color (e.g., dark green for success) with high-contrast text.
- **Lists:** Items should be separated by whitespace and a very faint `0.5px` line. Hover states should highlight the entire row with a subtle `rgba(255, 255, 255, 0.03)` fill.
- **AI-Specific Components:** Use "Prompt Bubbles" with a slight glassmorphism effect and "Thinking Indicators" that use a pulsing indigo glow.