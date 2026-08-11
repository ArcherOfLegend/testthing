// Proof that an authored shader reaches the screen: ignore everything the
// original did and return one colour. If the grid lines come out magenta, the
// whole path - author, compile, inject, draw - is working, and the only thing
// left between here and Blender-authored materials is generating the HLSL.
float4 main() : COLOR
{
    return float4(1.0f, 0.0f, 1.0f, 1.0f);
}
